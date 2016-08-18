import json
import logging

from decorator import decorator
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.WorkflowCore import WorkflowException
from Products.Five.browser import BrowserView
from Products.statusmessages.interfaces import IStatusMessage
from plone import api
from plone.dexterity.utils import createContentInContainer
from plone.registry.interfaces import IRegistry
from zope import contenttype
from zope.component import getUtility, queryUtility
from zope.publisher.interfaces import NotFound, BadRequest
from zope.schema.vocabulary import getVocabularyRegistry
from zope.schema.interfaces import IContextSourceBinder

from org.bccvl.site import defaults
from org.bccvl.site.api import dataset
from org.bccvl.site.browser.ws import IALAService, IGBIFService
from org.bccvl.site.content.interfaces import IDataset
from org.bccvl.site.interfaces import (
    IBCCVLMetadata, IExperimentJobTracker, IDownloadInfo)
from org.bccvl.site.job.interfaces import IJobTracker
from org.bccvl.site.swift.interfaces import ISwiftSettings
from org.bccvl.site.utils import decimal_encoder


LOG = logging.getLogger(__name__)

# self passed in as *args


@decorator  # well behaved decorator that preserves signature so that
# apply can inspect it
def returnwrapper(f, *args, **kw):
    # see http://code.google.com/p/mimeparse/
    # self.request.get['HTTP_ACCEPT']
    # self.request.get['CONTENT_TYPE']
    # self.request.get['method'']
    # ... decide on what type of call it is ... json?(POST),
    #     xmlrpc?(POST), url-call? (GET)

    # in case of post extract parameters and pass in?
    # jsonrpc:
    #    content-type: application/json-rpc (or application/json,
    #    application/jsonrequest) accept: application/json-rpc (or
    #    --""--)

    isxmlrpc = False
    view = args[0]
    try:
        ct = contenttype.parse.parse(view.request['CONTENT_TYPE'])
        if ct[0:2] == ('text', 'xml'):
            # we have xmlrpc
            isxmlrpc = True
    except Exception as e:
        # it's not valid xmlrpc
        # TODO: log this ?
        pass

    ret = f(*args, **kw)
    # return ACCEPT encoding here or IStreamIterator, that encodes
    # stuff on the fly could handle response encoding via
    # request.setBody ... would need to replace response instance of
    # request.response. (see ZPublisher.xmlprc.response, which wraps a
    # default Response)
    # FIXME: this is a bad workaround for - this method sholud be wrapped
    #        around tools and then be exposed as BrowserView ... ont as
    #        tool and BrowserView
    #        we call these wrapped functions internally, from templates and
    #        as ajax calls and xmlrpc calls, and expect different return
    #        encoding.
    #        ajax: json
    #        xmlrpc: xml, done by publisher
    #        everything else: python
    if not view.request['URL'].endswith(f.__name__):
        # not called directly, so return ret as is
        return ret

    # if we don't have xmlrpc we serialise to json
    if not isxmlrpc:
        ret = json.dumps(ret, default=decimal_encoder)
        view.request.response['CONTENT-TYPE'] = 'application/json'
    # FIXME: chaching headers should be more selective
    # prevent caching of ajax results... should be more selective here
    return ret


class DataSetManager(BrowserView):
    # DS Manager API on Site Root

    @returnwrapper
    # TODO: this method can be removed and use query(UID='') instead
    def metadata(self, datasetid):
        query = {'UID': datasetid}
        ds = dataset.query(self.context, **query)
        if ds:
            # we have a generator, let's pick the first result
            # metadata is extracted by query
            ds = next(ds, None)
        if ds is None:
            raise NotFound(self.context,  datasetid,  self.request)
        return ds

    # TODO: backwards compatible name
    @returnwrapper
    def getMetadata(self, datasetid):
        return self.metadata(datasetid)

    @returnwrapper
    def getRAT(self, datasetid, layer=None):
        query = {'UID': datasetid}
        dsbrain = dataset.query(self.context, brains=True, **query)
        if dsbrain:
            # get first brain from list
            dsbrain = next(dsbrain, None)
        if not dsbrain:
            raise NotFound(self.context, datasetid, self.request)
        md = IBCCVLMetadata(dsbrain.getObject())
        rat = md.get('layers', {}).get(layer, {}).get('rat')
        # if we have a rat, let's try and parse it
        if rat:
            try:
                rat = json.loads(unicode(rat))
            except Exception as e:
                LOG.warning(
                    "Couldn't decode Raster Attribute Table from metadata. %s: %s", self.context, repr(e))
                rat = None
        return rat

    @returnwrapper
    def query(self):
        # TODO: remove some parameters from request?
        #       e.g only matching with catalog indices
        #           only certain indices
        #       remove batching and internal parameters like brains
        query = self.request.form
        # TODO: should optimise this. e.g. return generator,
        objs = []
        for item in dataset.query(self.context, **query):
            objs.append(item)
        return objs

    @returnwrapper
    # TODO: need a replacement for this. it's a convenience function for UI
    def queryDataset(self, genre=None, layers=None):
        params = {'object_provides': IDataset.__identifier__}
        if genre:
            if not isinstance(genre, (tuple, list)):
                genre = (genre, )
            params['BCCDataGenre'] = {'query': genre,
                                      'operator': 'or'}
        if layers:
            if not isinstance(layers, (tuple, list)):
                layers = (layers, )
            params['BCCEnviroLayer'] = {'query': layers,
                                        'operator': 'and'}
        result = []
        for brain in dataset.query(self.context, True, **params):
            result.append({'uuid': brain.UID,
                           'title': brain.Title})
        return result

    # TODO: this is generic api ....
    @returnwrapper
    def getVocabulary(self, name):
        # TODO: check if there are vocabularies that need to be protected
        vocab = ()
        try:
            # TODO: getUtility(IVocabularyFactory???)
            vr = getVocabularyRegistry()
            vocab = vr.get(self.context, name)
        except:
            # eat all exceptions
            pass
        if not vocab:
            # try IContextSourceBinder
            vocab = queryUtility(IContextSourceBinder, name=name)
            if vocab is None:
                return []
            vocab = vocab(self.context)
        result = []
        for term in vocab:
            data = {'token': term.token,
                    'title': term.title}
            if hasattr(term, 'data'):
                data.update(term.data)
            result.append(data)
        return result


class DataSetAPI(BrowserView):
    # DS Manager API on Dataset

    @returnwrapper
    def getMetadata(self):
        return dataset.getdsmetadata(self.context)

    @returnwrapper
    def share(self):
        # TODO: status message and redirect are not useful for ajax
        msg = u"Status changed"
        msg_type = 'info'
        try:
            wtool = getToolByName(self.context, 'portal_workflow')
            wtool.doActionFor(self.context,  'publish')
        except WorkflowException as e:
            msg = u"Status change failed"
            msg_type = 'error'
        IStatusMessage(self.request).add(msg, type=msg_type)
        next = self.request['HTTP_REFERER']
        if not next or next == self.request['URL']:
            next = self.context.absolute_url()
        self.request.response.redirect(next)

    @returnwrapper
    def unshare(self):
        # TODO: status message and redirect are not useful for ajax
        msg = u"Status changed"
        msg_type = 'info'
        try:
            wtool = getToolByName(self.context, 'portal_workflow')
            wtool.doActionFor(self.context,  'retract')
        except WorkflowException as e:
            msg = u"Status change failed"
            msg_type = 'error'
        IStatusMessage(self.request).add(msg, type=msg_type)
        next = self.request['HTTP_REFERER']
        if not next or next == self.request['URL']:
            next = self.context.absolute_url()
        self.request.response.redirect(next)


class JobManagerAPI(BrowserView):
    # job manager on experiment

    @returnwrapper
    def getJobStatus(self):
        return IJobTracker(self.context).state

    @returnwrapper
    def getJobStates(self):
        return IExperimentJobTracker(self.context).states


from ZPublisher.Iterators import IStreamIterator
from zope.interface import implementer


@implementer(IStreamIterator)
class UrlLibResponseIterator(object):

    def __init__(self, resp):
        self.resp = resp
        try:
            self.length = int(resp.headers.getheader('Content-Length'))
        except:
            self.length = 0

    def __iter__(self):
        return self

    def next(self):
        data = self.resp.next()
        if not data:
            raise StopIteration
        return data

    def isError(self):
        return self.resp.code != 200

    def __len__(self):
        return self.length


class GBIFProxy(BrowserView):
    # @returnwrapper ... returning file here ... returnwrapper not handling it properly

    def autojson(self, q, callback=None):
        # TODO: do parameter checking and maybe set defaults so that
        # js side doesn't have to do it
        gbif = getUtility(IGBIFService)
        return self._doResponse(gbif.autojson(q, None, None, callback))

    # @returnwrapper ... returning file here ... returnwrapper not handling it properly
    def searchjson(self, name, start=0, pageSize=None, callback=None):
        # TODO: do parameter checking and maybe set defaults so that
        #       js side doesn't have to do it
        gbif = getUtility(IGBIFService)
        return self._doResponse(gbif.searchjson(name, None, start, pageSize, callback))

    def speciesjson(self, genusKey, start=0, pageSize=None, callback=None):
        gbif = getUtility(IGBIFService)
        return self._doResponse(gbif.speciesjson(genusKey, None, start, pageSize, callback))

    def _doResponse(self, resp):
        # TODO: add headers like:
        #    User-Agent
        #    orig-request
        #    etc...
        # TODO: check response code?
        for name in ('Date', 'Pragma', 'Expires', 'Content-Type',
                     'Cache-Control', 'Content-Language', 'Content-Length',
                     'transfer-encoding'):
            value = resp.headers.getheader(name)
            if value:
                self.request.response.setHeader(name, value)
        self.request.response.setStatus(resp.code)
        ret = UrlLibResponseIterator(resp)
        if len(ret) != 0:
            # we have a content-length so let the publisher stream it
            return ret
        # we don't have content-length and stupid publisher want's one
        # for stream, so let's stream it ourselves.
        while True:
            try:
                data = ret.next()
                self.request.response.write(data)
            except StopIteration:
                break


class ALAProxy(BrowserView):

    # @returnwrapper ... returning file here ... returnwrapper not handling it properly
    def autojson(self, q, geoOnly=None, idxType=None, limit=None,
                 callback=None):
        # TODO: do parameter checking and maybe set defaults so that
        # js side doesn't have to do it
        ala = getUtility(IALAService)
        return self._doResponse(ala.autojson(q, geoOnly, idxType, limit,
                                             callback))

    # @returnwrapper ... returning file here ... returnwrapper not handling it properly
    def searchjson(self, q, fq=None, start=None, pageSize=None,
                   sort=None, dir=None, callback=None):
        # TODO: do parameter checking and maybe set defaults so that
        #       js side doesn't have to do it
        ala = getUtility(IALAService)
        return self._doResponse(ala.searchjson(q, fq, start, pageSize,
                                               sort, dir, callback))

    def _doResponse(self, resp):
        # TODO: add headers like:
        #    User-Agent
        #    orig-request
        #    etc...
        # TODO: check response code?
        for name in ('Date', 'Pragma', 'Expires', 'Content-Type',
                     'Cache-Control', 'Content-Language', 'Content-Length',
                     'transfer-encoding'):
            value = resp.headers.getheader(name)
            if value:
                self.request.response.setHeader(name, value)
        self.request.response.setStatus(resp.code)
        ret = UrlLibResponseIterator(resp)
        if len(ret) != 0:
            # we have a content-length so let the publisher stream it
            return ret
        # we don't have content-length and stupid publisher want's one
        # for stream, so let's stream it ourselves.
        while True:
            try:
                data = ret.next()
                self.request.response.write(data)
            except StopIteration:
                break


class DataMover(BrowserView):

    @returnwrapper
    def pullOccurrenceFromALA(self, lsid, taxon, dataSrc='ala', common=None):
        # TODO: check permisions?
        # 1. create new dataset with taxon, lsid and common name set
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        if dataSrc == 'ala':
            dscontainer = portal[defaults.DATASETS_FOLDER_ID][defaults.DATASETS_SPECIES_FOLDER_ID]['ala']
        elif dataSrc == 'gbif':
            dscontainer = portal[defaults.DATASETS_FOLDER_ID][defaults.DATASETS_SPECIES_FOLDER_ID]['gbif']
        else:
            raise BadRequest('Invalid data source {0}'.format(dataSrc))

        title = [taxon]
        if common:
            title.append(u"({})".format(common))

        # TODO: move content creation into IALAJobTracker?
        # remotedataset?
        swiftsettings = getUtility(IRegistry).forInterface(ISwiftSettings)
        if swiftsettings.storage_url:
            portal_type = 'org.bccvl.content.remotedataset'
        else:
            portal_type = 'org.bccvl.content.dataset'

        # TODO: make sure we get a better content id that dataset-x
        ds = createContentInContainer(dscontainer,
                                      portal_type,
                                      title=u' '.join(title))
        ds.dataSource = dataSrc    # Either ALA or GBIF as source
        # TODO: add number of occurences to description
        ds.description = u' '.join(
            title) + u' imported from ' + unicode(dataSrc.upper())
        md = IBCCVLMetadata(ds)
        # TODO: provenance ... import url?
        # FIXME: verify input parameters before adding to graph
        md['genre'] = 'DataGenreSpeciesOccurrence'
        md['species'] = {
            'scientificName': taxon,
            'taxonID': lsid,
        }
        if common:
            md['species']['vernacularName'] = common
        IStatusMessage(self.request).add('New Dataset created',
                                         type='info')

        # 2. create and push alaimport job for dataset
        # TODO: make this named adapter
        jt = IExperimentJobTracker(ds)
        status, message = jt.start_job()
        # reindex object to make sure everything is up to date
        ds.reindexObject()
        # Job submission state notifier
        IStatusMessage(self.request).add(message, type=status)

        return (status, message)


class ExportResult(BrowserView):
    # TODO: should be post only? see plone.security for

    # parameters needed:
    #   ... serviceid ... service to export to

    # FIXME: should probably be a post only request?
    @returnwrapper
    def export_result(self, serviceid):
        # self.context should be a result
        if not hasattr(self.context, 'job_params'):
            raise NotFound(self.context, self.context.title, self.request)
        # TODO: validate serviceid

        # start export job
        context_path = '/'.join(self.context.getPhysicalPath())
        member = api.user.get_current()

        # collect list of files to export:
        urllist = []
        for content in self.context.values():
            if content.portal_type not in ('org.bccvl.content.dataset', 'org.bccvl.content.remotedataset'):
                # skip non datasets
                continue
            dlinfo = IDownloadInfo(content)
            urllist.append(dlinfo['url'])
        # add mets.xml
        urllist.append('{}/mets.xml'.format(self.context.absolute_url()))
        # add prov.ttl
        urllist.append('{}/prov.ttl'.format(self.context.absolute_url()))

        from org.bccvl.tasks.celery import app
        from org.bccvl.tasks.plone import after_commit_task
        # FIXME: Do mapping from serviceid to service type? based on interface
        #        background task will need serviceid and type, but it may resolve
        #        servicetype via API with serviceid
        export_task = app.signature(
            "org.bccvl.tasks.export_services.export_result",
            kwargs={
                'siteurl': api.portal.get().absolute_url(),
                'fileurls': urllist,
                'serviceid': serviceid,
                'context': {
                    'context': context_path,
                    'user': {
                        'id': member.getUserName(),
                        'email': member.getProperty('email'),
                        'fullname': member.getProperty('fullname')
                    }
                }
            },
            options={'immutable': True})

        # queue job submission
        after_commit_task(export_task)

        # self.new_job('TODO: generate id', 'generate taskname: export_result')
        # self.set_progress('PENDING', u'Result export pending')

        status = 'info'
        message = u'Export request for "{}" succesfully submitted! Please check the service and any associated email accounts to confirm the data\'s availability'.format(
            self.context.title)

        IStatusMessage(self.request).add(message, type=status)
        nexturl = self.request.get('HTTP-REFERER')
        if not nexturl:
            # this method should only be called on a result folder
            # we should be able to safely redirect back to the pacent
            # experiment
            nexturl = self.context.__parent__.absolute_url()
        self.request.response.redirect(nexturl, 307)
        return (status, message)
