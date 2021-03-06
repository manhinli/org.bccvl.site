# -*- coding: utf-8 -*-
import logging
import shutil
import tempfile

from Acquisition import aq_inner
from Products.CMFCore.utils import getToolByName
from Products.Five import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.statusmessages.interfaces import IStatusMessage

from plone import api
from plone.app.dexterity.behaviors.metadata import IDublinCore
from plone.dexterity.browser.add import DefaultAddForm
from plone.dexterity.utils import addContentToContainer
from plone.registry.interfaces import IRegistry
from plone.uuid.interfaces import IUUID
from z3c.form import button
from z3c.form.field import Fields
from zope.component import getUtility
from zope.schema import Bool

from org.bccvl import movelib
from org.bccvl.movelib.utils import build_source, build_destination
from org.bccvl.site import defaults
from org.bccvl.site.interfaces import IBCCVLMetadata, IDownloadInfo
from org.bccvl.site.content.interfaces import IBlobDataset
from org.bccvl.site.content.interfaces import IMultiSpeciesDataset
from org.bccvl.site.content.dataset import (
    ISpeciesDataset,
    ISpeciesCollection,
    ILayerDataset,
    ITraitsDataset)
from org.bccvl.site.swift.interfaces import ISwiftSettings
from org.bccvl.site.utils import get_results_dir
from org.bccvl.tasks.celery import app
from org.bccvl.site.job.interfaces import IJobTracker
from org.bccvl.tasks.plone import after_commit_task


LOG = logging.getLogger(__name__)


# TODO: provenance field:
#       -> created by experiment, imported from ALA, uploaded by user,
#          provided by system

class BCCVLUploadForm(DefaultAddForm):

    # #form.extends(DefaultAddForm, ignoreButtons=True)
    # buttons = button.Buttons(DefaultAddForm.buttons['cancel'])

    css_class = 'form-horizontal'

    template = ViewPageTemplateFile('dataset_upload_subform.pt')

    datagenre = None

    timeperiod = None

    def create(self, data):
        self.domain = None
        if self.datagenre in ('DataGenreCC', 'DataGenreFC', 'DataGenreE'):
            self.domain = data.get('domain', None)

        if self.portal_type == 'org.bccvl.content.remotedataset':
            # we are going to create a remote dataset from an upload
            # 1. put upload information aside; will be processed in add
            self._upload = {'file': data['file']}
            del data['file']

        # this method only applies fields from the form ,....
        #     we have to apply other attributes manually
        obj = super(BCCVLUploadForm, self).create(data)
        obj.dataSource ='upload'
        return obj

    def add(self, object):
        # FIXME: this is a workaround, which is fine for small uploaded files.
        #        large uploads should go through another process anyway
        # TODO: re implementing this method is the only way to know
        #       the full path of the object. We need the path to apply
        #       the transmogrifier chain.
        # fti = getUtility(IDexterityFTI, name=self.portal_type)
        container = aq_inner(self.context)
        try:
            # traverse to subfolder if possible
            container = container.restrictedTraverse('/'.join(self.subpath))
        except Exception as e:
            LOG.warn('Could not traverse to %s/%s',
                     '/'.join(container.getPhysicalPath()), '/'.join(self.subpath))
        new_object = addContentToContainer(container, object)
        # set data genre:
        if self.datagenre:
            IBCCVLMetadata(new_object)['genre'] = self.datagenre
        if self.categories:
            IBCCVLMetadata(new_object)['categories'] = self.categories
        
        new_object.subject = []
        if self.domain:
            new_object.subject = [self.domain]
        if self.timeperiod:
            new_object.subject += self.timeperiod

            # rdf commit should happens in transmogrifier step later on
        # if fti.immediate_view:
        #     self.immediate_view = "%s/%s/%s" % (container.absolute_url(), new_object.id, fti.immediate_view,)
        # else:
        #     self.immediate_view = "%s/%s" % (container.absolute_url(), new_object.id)
        # start background import process (just a metadata update)

        # run transmogrify md extraction here
        context_path = '/'.join(new_object.getPhysicalPath())
        member = api.user.get_current()
        # species extract task
        if IMultiSpeciesDataset.providedBy(new_object):
            # kick off csv split import tasks
            import_task = app.signature(
                "org.bccvl.tasks.datamover.tasks.import_multi_species_csv",
                kwargs={
                    'url': '{}/@@download/file/{}'.format(new_object.absolute_url(), new_object.file.filename),
                    'results_dir': get_results_dir(new_object, self.request, childSpecies=True),
                    'import_context': {
                        'context': '/'.join(container.getPhysicalPath()),
                        'user': {
                            'id': member.getUserName(),
                            'email': member.getProperty('email'),
                            'fullname': member.getProperty('fullname')
                        }
                    },
                    'context': {
                        'context': context_path,
                        'genre': self.datagenre,
                        'dataSource': new_object.dataSource,
                        'user': {
                            'id': member.getUserName(),
                            'email': member.getProperty('email'),
                            'fullname': member.getProperty('fullname')
                        }
                    }
                },
                immutable=True)
            after_commit_task(import_task)
            # create job tracking object
            jt = IJobTracker(new_object)
            jt.new_job('TODO: generate id',
                       'generate taskname: import_multi_species_csv',
                       function=new_object.dataSource,
                       type=new_object.portal_type)
            jt.set_progress('PENDING', u'Multi species import pending')
        else:
            if hasattr(self, '_upload'):
                file = self._upload['file']
                new_object.format = file.contentType
                uid = IUUID(new_object)
                swiftsettings = getUtility(
                    IRegistry).forInterface(ISwiftSettings)
                import os.path
                swift_url = '{storage_url}/{container}/{path}/{name}'.format(
                    storage_url=swiftsettings.storage_url,
                    container=swiftsettings.result_container,
                    path=uid,
                    name=os.path.basename(file.filename))
                new_object.remoteUrl = swift_url
            else:
                file = new_object.file
                new_object.format = file.contentType

            dlinfo = IDownloadInfo(new_object)

            # single species upload
            update_task = app.signature(
                "org.bccvl.tasks.datamover.tasks.update_metadata",
                kwargs={
                    'url': dlinfo['url'],
                    'filename': dlinfo['filename'],
                    'contenttype': dlinfo['contenttype'],
                    'context': {
                        'context': context_path,
                        'user': {
                            'id': member.getUserName(),
                            'email': member.getProperty('email'),
                            'fullname': member.getProperty('fullname')
                        }
                    }
                },
                immutable=True)
            # create upload task in case we upload to external store
            if hasattr(self, '_upload'):
                # FIXME: we can't use ssh here.... we don't know which container we are in... and
                #        sshing here is bad as well....
                # There is an upload ... we have to make sure the uploaded data ends up in external storage
                # 3. put temp file aside
                tmpdir = tempfile.mkdtemp(prefix='bccvl_upload')
                tmpfile = os.path.join(tmpdir, os.path.basename(file.filename))
                blobf = file.open()
                try:
                    # try rename
                    os.rename(blobf.name, tmpfile)
                except OSError:
                    # try copy
                    shutil.copy(blobf.name, tmpfile)

                # TODO: we push the uploaded file directly to swift here..
                #       this really should be a background process
                #       best solution: ...
                #           user uploads to some temporary upload service (file never ends up here)
                #           we have a remote url here, and tell the datamover to pull it from there
                #           and move it to final destination. (or something like this)
                #       other good way: ...
                #           let user upload directly to swift (what about large file uploads?)
                #           and take care of clean up if necessary

                # 4. move file to swift
                # TODO: do we have enough information to upload to swift?
                #       need a temp url?
                swiftopts = app.conf.get('bccvl', {}).get('swift', {})
                src_url = build_source('file://{}'.format(tmpfile))
                dest_url = build_destination('swift+{}'.format(new_object.remoteUrl),
                    settings={'swift': {
                        'os_auth_url': swiftopts.get('os_auth_url'),
                        'os_username': swiftopts.get('os_username'),
                        'os_password': swiftopts.get('os_password'),
                        'os_tenant_name': swiftopts.get('os_tenant_name'),
                        'os_storage_url': swiftopts.get('os_storage_url')
                    }}
                )

                try:
                    movelib.move(src_url, dest_url)
                except Exception as e:
                    # do error handling here
                    raise
                finally:
                    # clean up temp location
                    path = os.path.dirname(tmpfile)
                    shutil.rmtree(path)

            # queue job submission
            after_commit_task(update_task)
            # create job tracking object
            jt = IJobTracker(new_object)
            jt.new_job('TODO: generate id',
                       'generate taskname: update_metadata',
                       function=new_object.dataSource,
                       type=new_object.portal_type)
            jt.set_progress('PENDING', u'Metadata update pending')

        # We have to reindex after updating the object
        new_object.reindexObject()

    def nextURL(self):
        # redirect to default datasets page
        portal = getToolByName(self.context, 'portal_url').getPortalObject()
        return portal[defaults.DATASETS_FOLDER_ID].absolute_url()

    def updateWidgets(self):
        super(BCCVLUploadForm, self).updateWidgets()
        self.widgets['description'].rows = 6
        # self.widgets['rights'].rows = 6

    def updateActions(self):
        super(BCCVLUploadForm, self).updateActions()
        self.actions['save'].disabled = "disabled"

    def updateFields(self):
        # don't fetch plone default fields'
        self.fields += Fields(
            Bool(
                __name__='legalcheckbox',
                title=u'I agree to the <a href="http://www.bccvl.org.au/about/legal/terms-of-use/" target="_blank">Terms and Conditions</a>',
                required=True,
                default=False
            )
        )
        # ITermsAndConditions, ignoreContext=True)

    @button.buttonAndHandler(u'Save', name='save')
    def handleAdd(self, action):
        data, errors = self.extractData()
        if errors:
            self.status = self.formErrorsMessage
            return
        # FIXME: here is a good place to validate TermsAndConditions
        # FIXME: legalcheckbox should probably not be in self.fields, but
        # rather a manually created and validated checkbox in the form template
        del data['legalcheckbox']
        obj = self.createAndAdd(data)
        if obj is not None:
            # mark only as finished if we get the new object
            self._finishedAdd = True
            IStatusMessage(self.request).addStatusMessage(
                u"Item created", "info success"
            )

    @button.buttonAndHandler(u'Cancel', name='cancel')
    def handleCancel(self, action):
        # We call a ButtonHandler not a method on super, so we have to pass in
        # self as well
        super(BCCVLUploadForm, self).handleCancel(
            self, action)  # self, form, action


class SpeciesAbsenceAddForm(BCCVLUploadForm):

    title = u"Upload Species Absence Data"
    description = (
        u"<p>Upload absence data for single species</p>"
        u"<h4>Instructions:</h4>"
        u"<ul><li>Format needs to be .csv</li>"
        u"<li>REQUIRED: Two columns with exact labels ‘lat’ and ‘lon’</li>"
        u"<li>OPTIONAL: third column with exact label 'month' (used in Migratory Modelling Experiment)</li>"
        u"<li>Coordinates in decimal degrees</li></p>"
    )
    fields = Fields(IBlobDataset, IDublinCore, ISpeciesDataset).select(
        'file', 'title', 'description', 'scientificName', 'taxonID',
        'vernacularName', 'rights')
    datagenre = 'DataGenreSpeciesAbsence'
    categories = ['absence']
    subpath = [defaults.DATASETS_SPECIES_FOLDER_ID, 'user']


class SpeciesAbundanceAddForm(BCCVLUploadForm):

    title = u"Upload Species Abundance Data"
    description = (
        u"<p>Upload abundance data for single species</p>"
        u"<p>An abundance dataset is expected to be in CSV format."
        u"Your longitude and latitude must be in decimal degrees."
        u"The BCCVL will only try to interpret columns with labels "
        u"'lon' and 'lat', so ensure your headings match these labels.</p>"
    )
    fields = Fields(IBlobDataset, IDublinCore, ISpeciesDataset).select(
        'file', 'title', 'description', 'scientificName', 'taxonID',
        'vernacularName', 'rights')
    datagenre = 'DataGenreSpeciesAbundance'
    categories = ['abundance']


class SpeciesOccurrenceAddForm(BCCVLUploadForm):

    title = u"Upload Species Occurrence Data"
    description = (
        u"<p>Upload occurrence data for single species</p>"
        u"<h4>Instructions:</h4>"
        u"<ul><li>Format needs to be .csv</li>"
        u"<li>REQUIRED: Two columns with exact labels ‘lat’ and ‘lon’</li>"
        u"<li>OPTIONAL: third column with exact label 'month' (used in Migratory Modelling Experiment)</li>"
        u"<li>Coordinates in decimal degrees</li></p>"
    )
    fields = Fields(IBlobDataset, IDublinCore, ISpeciesDataset).select(
        'file', 'title', 'description', 'scientificName', 'taxonID',
        'vernacularName', 'rights')
    datagenre = 'DataGenreSpeciesOccurrence'
    categories = ['occurrence']
    subpath = [defaults.DATASETS_SPECIES_FOLDER_ID, 'user']


class MultiSpeciesOccurrenceAddForm(BCCVLUploadForm):

    title = u"Upload Multiple Species Occurence Data"
    description = (
        u"<p>Upload occurrences data for multiple species</p>"
        u"<h4>Instructions:</h4>"
        u"<ul><li>Format needs to be .csv</li>"
        u"<li>Three columns with exact labels 'species', ‘lat’ and ‘lon’</li>"
        u"<li>Coordinates in decimal degrees</li></p>"
    )
    fields = Fields(IMultiSpeciesDataset, IDublinCore, ISpeciesCollection).select(
        'file', 'title', 'description', 'rights')
    datagenre = 'DataGenreSpeciesCollection'
    categories = ['multispecies']
    subpath = [defaults.DATASETS_SPECIES_FOLDER_ID, 'user']

class MultiSpeciesAbsenceAddForm(BCCVLUploadForm):

    title = u"Upload Multiple Species Absence Data"
    description = (
        u"<p>Upload absence data for multiple species</p>"
        u"<h4>Instructions:</h4>"
        u"<ul><li>Format needs to be .csv</li>"
        u"<li>Three columns with exact labels 'species', ‘lat’ and ‘lon’</li>"
        u"<li>Coordinates in decimal degrees</li></p>"
    )
    fields = Fields(IMultiSpeciesDataset, IDublinCore, ISpeciesCollection).select(
        'file', 'title', 'description', 'rights')
    datagenre = 'DataGenreSpeciesAbsenceCollection'
    categories = ['absence']
    subpath = [defaults.DATASETS_SPECIES_FOLDER_ID, 'user']

class ClimateCurrentAddForm(BCCVLUploadForm):

    title = u"Upload Current Climate Data"
    description = (
        u"<p>Upload current climate data</p>"
        u"<p>BCCVL can only deal with raster data in GeoTIFF format."
        u" Valid files are either single GeoTiff files or a number of"
        u" GeoTiff packaged within a zip file.</p>"
        u"<p>It is easy to convert your csv files to GeoTIFF format,"
        u"follow the instructions here <a href=\"https://github.com/NICTA/nationalmap/wiki/csv-geo-au\" target=\"_blank\">https://github.com/NICTA/nationalmap/wiki/csv-geo-au</a>."
        u"  Ideally the map projection information is embedded as metadata within the GeoTiff itself. In case of missing map projection BCCVL assumes WGS-84 (EPSG:4326).,</p>")

    fields = Fields(IBlobDataset, IDublinCore, ILayerDataset).select(
        'domain', 'file', 'title', 'description', 'resolution', # 'resolutiono',
        'rights')
    datagenre = 'DataGenreCC'
    categories = ['climate']
    timeperiod = ['Current datasets']

    # datatype, gcm, emissionscenario
    subpath = [defaults.DATASETS_CLIMATE_FOLDER_ID, 'user']


class EnvironmentalAddForm(BCCVLUploadForm):

    title = u"Upload Environmental Data"
    description = (
        u"<p>Upload environmental data</p>"
        u"<p>BCCVL can only deal with raster data in GeoTIFF format."
        u" Valid files are either single GeoTiff files or a number of"
        u" GeoTiff packaged within a zip file.</p>"
        u"Ideally the map projection information is embedded as metadata within the GeoTiff itself. In case of missing map projection BCCVL assumes WGS-84 (EPSG:4326).,</p>")

    fields = Fields(IBlobDataset, IDublinCore, ILayerDataset).select(
        'domain', 'file', 'title', 'description', 'resolution', # 'resolutiono',
        'rights')
    datagenre = 'DataGenreE'
    categories = ['environmental']
    timeperiod = ['Current datasets']

    # datatype, gcm, emissionscenario
    subpath = [defaults.DATASETS_ENVIRONMENTAL_FOLDER_ID, 'user']

class EnvironmentalFutureAddForm(BCCVLUploadForm):

    title = u"Upload Future Environmental Data"
    description = (
        u"<p>Upload future environmental data</p>"
        u"<p>BCCVL can only deal with raster data in GeoTIFF format."
        u" Valid files are either single GeoTiff files or a number of"
        u" GeoTiff packaged within a zip file.</p>"
        u"Ideally the map projection information is embedded as metadata within the GeoTiff itself. In case of missing map projection BCCVL assumes WGS-84 (EPSG:4326).,</p>")

    fields = Fields(IBlobDataset, IDublinCore, ILayerDataset).select(
        'domain', 'file', 'title', 'description', 'emsc', 'gcm',
        'resolution', # 'resolutiono',
        'rights')
    datagenre = 'DataGenreE'
    categories = ['environmental']
    timeperiod = ['Future datasets']

    # datatype, gcm, emissionscenario
    subpath = [defaults.DATASETS_ENVIRONMENTAL_FOLDER_ID, 'user']



class ClimateFutureAddForm(BCCVLUploadForm):

    title = u"Upload Future Climate Data"
    description = (
        u"<p>Upload future climate data</p>"
        u"<p>BCCVL can only deal with raster data in GeoTIFF format."
        u" Valid files are either single GeoTiff files or a number of"
        u" GeoTiff packaged within a zip file.</p>"
        u"<p>It is easy to convert your csv files to GeoTIFF format,"
        u"follow the instructions here <a href=\"https://github.com/NICTA/nationalmap/wiki/csv-geo-au\" target=\"_blank\">https://github.com/NICTA/nationalmap/wiki/csv-geo-au</a>."
        u"Ideally the map projection information is embedded as metadata within the GeoTiff itself. In case of missing map projection BCCVL assumes WGS-84 (EPSG:4326).,</p>")

    fields = Fields(IBlobDataset, IDublinCore, ILayerDataset).select(
         'domain', 'file', 'title', 'description', 'emsc', 'gcm',
        'resolution', # 'resolutiono',
        'rights')
    datagenre = 'DataGenreFC'
    categories = ['climate']
    timeperiod = ['Future datasets']

    # datatype, gcm, emissionscenario
    subpath = [defaults.DATASETS_CLIMATE_FOLDER_ID, 'user']


class SpeciesTraitAddForm(BCCVLUploadForm):
    # TODO: these wolud be schema forms... sholud try it

    title = u"Upload Species Traits"
    description = (
        u"<p>Upload trait data for one or multiple species.</p>"
        u"<h4>Instructions:</h4>"
        u"<ul><li>Format needs to be .csv</li>"
        u"<li>Three columns with exact labels 'species', ‘lat’ and ‘lon’</li>"
        u"<li>Additional columns with trait and (optionally) environmental data</li>"
        u"<li>Coordinates in decimal degrees</li></p>"
    )

    fields = Fields(IBlobDataset, IDublinCore, ITraitsDataset).select(
        'file', 'title', 'description', 'rights')
    datagenre = 'DataGenreTraits'
    categories = ['traits']
    subpath = [defaults.DATASETS_SPECIES_FOLDER_ID, 'user']


class DatasetsUploadView(BrowserView):
    """
    upload datasets view
    """
    # forms:
    #-> environmental, future climate,
    #-> future projection, output log file
    #-> species distribution, species distribution model evaluation,
    #-> species occurence
    # common accross all forms:
    #-> title, description, file, format,

    #-> use defaultform, extend updateFields to select only wanted fileds?
    #-> use standard form, create fields manually

    title = u"Upload Dataset"

    subforms = None

    def update(self):
        self.subforms = []
        ttool = getToolByName(self.context, 'portal_types')

        # decide whether we store content in db or in object store
        swiftsettings = getUtility(IRegistry).forInterface(ISwiftSettings)
        ds_portal_type = 'org.bccvl.content.dataset'
        if swiftsettings.storage_url:
            ds_portal_type = 'org.bccvl.content.remotedataset'

        for form_prefix, form_class, portal_type in (
                ('speciesabsence', SpeciesAbsenceAddForm, ds_portal_type),
                ('speciesabundance', SpeciesAbundanceAddForm, ds_portal_type),
                ('speciesoccurrence', SpeciesOccurrenceAddForm, ds_portal_type),
                ('multispeciesoccurrence', MultiSpeciesOccurrenceAddForm,
                 'org.bccvl.content.multispeciesdataset'),
                ('multispeciesabsence', MultiSpeciesAbsenceAddForm,
                 'org.bccvl.content.multispeciesdataset'),
                ('climatecurrent', ClimateCurrentAddForm, ds_portal_type),
                ('environmental', EnvironmentalAddForm, ds_portal_type),
                ('climatefuture', ClimateFutureAddForm, ds_portal_type),
                ('environmentalfuture', EnvironmentalFutureAddForm, ds_portal_type),
                ('speciestrait', SpeciesTraitAddForm, ds_portal_type)):
            fti = ttool.getTypeInfo(portal_type)
            form = form_class(aq_inner(self.context),
                              self.request, fti)
            form.__name__ = "{0}form".format(form_prefix)
            form.prefix = form_prefix
            self.subforms.append(form)
            # always update all forms in case we return and want to preserve
            # entered values
            form.update()

        # render the forms for display or generate redirect
        for idx, subform in enumerate(self.subforms):
            self.subforms[idx] = {'content': subform.render(),
                                  'title': subform.title}

    def __call__(self):
        self.update()
        # if one of our subforms initiated a redirect follow it
        if self.request.response.getStatus() in (302, 303):
            return
        return super(DatasetsUploadView, self).__call__()
