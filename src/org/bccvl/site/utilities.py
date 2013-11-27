from gu.plone.rdf.interfaces import IRDFContentTransform
from rdflib import RDF, RDFS, Literal, OWL
from ordf.namespace import FOAF
from org.bccvl.site.content.user import IBCCVLUser
from org.bccvl.site.content.group import IBCCVLGroup
from org.bccvl.site.content.experiment import IExperiment
from org.bccvl.site.content.dataset import IDataset
from org.bccvl.site.interfaces import IJobTracker
from gu.repository.content.interfaces import (
    IRepositoryContainer,
    IRepositoryItem,
    )
from plone.app.uuid.utils import uuidToObject
from zc.async.interfaces import COMPLETED
from zope.component import adapter
from zope.interface import implementer
from zope.dottedname.resolve import resolve
from gu.plone.rdf.namespace import CVOCAB
from ordf.namespace import DC as DCTERMS
from gu.z3cform.rdf.interfaces import IRDFTypeMapper
from plone.app.contenttypes.interfaces import IFile


@implementer(IRDFTypeMapper)
class RDFTypeMapper(object):

    def __init__(self, context, request, form):
        self.context = context
        self.request = request
        self.form = form

    def applyTypes(self, graph):
        pt = self.form.portal_type
        typemap = {'org.bccvl.content.user': FOAF['Person'],
                   'org.bccvl.content.group': FOAF['Group'],
                   'org.bccvl.content.dataset': CVOCAB['Dataset'],
                   # TODO: remove types below someday
                   'gu.repository.content.RepositoryItem': CVOCAB['Item'],
                   'gu.repository.content.RepositoryContainer': CVOCAB['Collection'],
                   'File': CVOCAB['File']}
        rdftype = typemap.get(pt, OWL['Thing'])
        graph.add((graph.identifier, RDF['type'], rdftype))


@implementer(IRDFContentTransform)
class RDFContentBasedTypeMapper(object):

    def tordf(self, content, graph):
        # We might have a newly generated empty graph here, so let's apply the
        # all IRDFTypeMappers as well
        if IDataset.providedBy(content):
            graph.add((graph.identifier, RDF['type'], CVOCAB['Dataset']))
        elif IBCCVLUser.providedBy(content):
            graph.add((graph.identifier, RDF['type'], FOAF['Person']))
        elif IBCCVLGroup.providedBy(content):
            graph.add((graph.identifier, RDF['type'], FOAF['Group']))  # foaf:Organization
        # TODO: remove types below some day
        elif IRepositoryItem.providedBy(content):
            graph.add((graph.identifier, RDF['type'], CVOCAB['Item']))
        elif IRepositoryContainer.providedBy(content):
            graph.add((graph.identifier, RDF['type'], CVOCAB['Collection']))
        elif IFile.providedBy(content):
            graph.add((graph.identifier, RDF['type'], FOAF['File']))

        graph.add((graph.identifier, RDF['type'], OWL['Thing']))


@implementer(IRDFContentTransform)
class RDFDataMapper(object):

    def tordf(self, content, graph):
        # FIXME: use only one way to describe things ....
        #        see dc - rdf mapping at http://dublincore.org/documents/dcq-rdf-xml/
        #        maybe dc app profile not as good as it might sound, but translated to RDF is better (or even owl)
        # FIXME: maybe move the next part into a separate utility
        # TODO: check content for attributes/interface before trying to access them
        for prop, val in ((DCTERMS['title'], Literal(content.title)),
                          (RDFS['label'], Literal(content.title)),
                          (DCTERMS['description'], Literal(content.description)),
                          (RDFS['comment'], Literal(content.description)),
                          ):
            if not graph.value(graph.identifier, prop):
                graph.add((graph.identifier, prop, val))


@adapter(IExperiment)
@implementer(IJobTracker)
class JobTracker(object):

    def __init__(self, context):
        self.context = context

    def start_job(self):
        if not self.has_active_jobs():
            self.context.current_jobs = []
            for func in (uuidToObject(f) for f in self.context.functions):
                # TODO: default queue quota is 1. either set it to a defined value (see: plone.app.asnc.subscriber)
                #       or create and submit job manually
                #job = async.queueJob(execute, self.context, envfile, specfile)
                method = None
                if func is None:
                    return ('error',
                            u"Can't find function {}".format(self.context.functions))
                else:
                    if not func.compute_function.startswith('org.bccvl.compute'):
                        return ('error',
                                u"ComputeFunction '{}' not in compute package".format(func.compute_function))
                    try:
                        # TODO: check interface?
                        method = resolve(func.compute_function).execute
                    except ImportError:
                        return ('error',
                                u"Can't resolve ComputeFunction '{}'".format(func.compute_function))
                if method is None:
                    return 'error', u"Unknown error, method is None"

                # submit job to queue
                job = method(self.context)
                self.context.current_jobs.append(job)
            return 'info', u'Job submitted {}'.format(self.status())
        else:
            return 'error', u'Current Job is still running'

    def status(self):
        from zope.i18n import translate
        status = []
        for job in self.get_jobs():
            status.append((job.jobid, job.annotations['bccvl.status']['task']))
        return status

    def get_jobs(self):
        return getattr(self.context, 'current_jobs', [])

    def has_active_jobs(self):
        active = False
        for job in self.get_jobs():
            if job.status not in (None, COMPLETED):
                active = True
                break
        return active
