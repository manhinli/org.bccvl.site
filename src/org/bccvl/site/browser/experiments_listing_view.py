from Products.Five import BrowserView
from Products.CMFPlone.interfaces import IPloneSiteRoot
from Products.CMFCore.utils import getToolByName
from Products.ZCatalog.interfaces import ICatalogBrain
from plone.app.content.browser.interfaces import IFolderContentsView
from zope.interface import implementer
from plone.app.uuid.utils import uuidToObject, uuidToCatalogBrain
from plone.app.contenttypes.browser.folder import FolderView
from plone.app.contentlisting.interfaces import IContentListing
from plone.app.contentlisting.interfaces import IContentListingObject
from org.bccvl.site.interfaces import IBCCVLMetadata
from org.bccvl.site.content.interfaces import IExperiment
from org.bccvl.site.interfaces import IExperimentJobTracker
from collections import defaultdict
from zope.component import queryUtility, getMultiAdapter
from org.bccvl.site import defaults
from itertools import chain
from org.bccvl.site.browser.interfaces import IExperimentTools
from zope.security import checkPermission


def get_title_from_uuid(uuid, default=None):
    try:
        obj = uuidToCatalogBrain(uuid)
        if obj:
            return obj.Title
    except Exception as e:
        pass
    return default


@implementer(IExperimentTools)
class ExperimentTools(BrowserView):

    def check_if_used(self, itemob=None):
        itemob = itemob or self.context
        portal_catalog = getToolByName(itemob, 'portal_catalog')
        return len(list(portal_catalog.unrestrictedSearchResults(experiment_reference=itemob.UID()))) > 0

    def get_depending_experiment_titles(self, itemob=None):
        itemob = itemob or self.context
        portal_catalog = getToolByName(itemob, 'portal_catalog')
        ur = list(portal_catalog.unrestrictedSearchResults(experiment_reference=itemob.UID()))
        rrpaths = map(lambda x: x.getPath(), portal_catalog.searchResults(experiment_reference=itemob.UID()))
        return map(lambda x: x.Title if x.getPath() in rrpaths else "(Private - owned by %s)" % x._unrestrictedGetObject().getOwner().getUserName(), ur)

    def can_modify(self, itemob=None):
        try:
            itemob = itemob or self.context
            return checkPermission('cmf.ModifyPortalContent', itemob)
        except Exception as e:
            return False

    def get_state_css(self, itemob=None):
        itemob = itemob or self.context
        if ICatalogBrain.providedBy(itemob) or IContentListingObject.providedBy(itemob):
            job_state = itemob.job_state
        else:
            job_state = IExperimentJobTracker(itemob).state
        css_map = {
            None: 'success',
            'QUEUED': 'warning',
            'RUNNING': 'warning',
            'PARTIAL': 'warning',
            'COMPLETED': 'success',
            'FAILED': 'error',
            'REMOVED': 'removed',
            'FINISHED': 'info'
        }
        # check job_state and return either success, error or block
        return css_map.get(job_state, 'info')

    def experiment_details(self, expbrain):
        details = {}
        if expbrain.portal_type == 'org.bccvl.content.projectionexperiment':
            details = projection_listing_details(expbrain)
        elif expbrain.portal_type == 'org.bccvl.content.sdmexperiment':
            details = sdm_listing_details(expbrain)
        elif expbrain.portal_type == 'org.bccvl.content.msdmexperiment':
            # FIXME: ... need msdm listing details here
            details = msdm_listing_details(expbrain)
        elif expbrain.portal_type == 'org.bccvl.content.mmexperiment':
            details = mme_listing_details(expbrain)
        elif expbrain.portal_type == 'org.bccvl.content.biodiverseexperiment':
            details = biodiverse_listing_details(expbrain)
        elif expbrain.portal_type == 'org.bccvl.content.ensemble':
            details = ensemble_listing_details(expbrain)
        elif expbrain.portal_type == 'org.bccvl.content.speciestraitsexperiment':
            details = speciestraits_listing_details(expbrain)
        return details


@implementer(IFolderContentsView)
class ExperimentsListingView(FolderView):

    title = u"Experiment List"

    def __init__(self, context, request):
        # update limit_display if it is not already set
        limit_display = getattr(request, 'limit_display', None)
        if limit_display is None:
            request.limit_display = 100
        super(ExperimentsListingView, self).__init__(context, request)

    def new_experiment_actions(self):
        experimenttypes = ('org.bccvl.content.sdmexperiment',
                           'org.bccvl.content.msdmexperiment',
                           'org.bccvl.content.mmexperiment',
                           'org.bccvl.content.projectionexperiment',
                           'org.bccvl.content.ensemble',
                           'org.bccvl.content.biodiverseexperiment',
                           'org.bccvl.content.speciestraitsexperiment')
        ftool = getMultiAdapter((self.context, self.request),
                                name='folder_factories')
        actions = ftool.addable_types(experimenttypes)
        return dict((action['id'], action) for action in actions)

    def results(self, **kwargs):
        # set our search filters in kwargs and pass on to super class
        kwargs.update({
            'path': {
                'query': '/'.join((self.portal_state.navigation_root_path(),
                                   defaults.EXPERIMENTS_FOLDER_ID))
            },
            'object_provides': IExperiment.__identifier__,
            'sort_on': 'created',
            'sort_order': 'descending',
        })
        return super(ExperimentsListingView, self).results(**kwargs)


# FIXME: the methods below, should be looked up via named adapter or similar.
#        furthermore, in the experimentlisting view it might be good to use
#        templates / or macros that are lookup up via (view, request, context)
#        to support different list item rendering based on view and context (re-use on listing page and popup listing?)

def sdm_listing_details(expbrain):
    # TODO: this is ripe for optimising so it doesn't run every time
    # experiments are listed
    details = {}
    exp = expbrain.getObject()
    if exp.environmental_datasets:
        details.update({
            'type': 'SDM',
            'functions': ', '.join(
                get_title_from_uuid(func, u'(Unavailable)') for func in exp.functions
                if func),
            'species_occurrence': get_title_from_uuid(
                exp.species_occurrence_dataset, u'(Unavailable)') if exp.species_occurrence_dataset else '',
            'species_absence': get_title_from_uuid(
                exp.species_absence_dataset, u'(Unavailable)') if exp.species_absence_dataset else '',
            'environmental_layers': ({
                'title': get_title_from_uuid(dataset, u'(Unavailable)'),
                'layers': sorted(layers)
            } for dataset, layers in exp.environmental_datasets.items()
            ),
        })
    return details


def msdm_listing_details(expbrain):
    # TODO: this is ripe for optimising so it doesn't run every time
    # experiments are listed
    details = {}
    exp = expbrain.getObject()
    if exp.environmental_datasets:
        try:
            species_titles = ', '.join(get_title_from_uuid(ds, u'(Unavailable)')
                                       for ds in exp.species_occurrence_collections
                                       if ds)
        except Exception as e:
            species_titles = ''
        details.update({
            'type': 'MSDM',
            'functions': get_title_from_uuid(exp.function, u'(Unavailable)') if exp.function else '',
            'species_occurrence': species_titles,
            'species_absence': get_title_from_uuid(
                exp.species_absence_collection, u'(Unavailable)') if exp.species_absence_collection else '',
            'environmental_layers': ({
                'title': get_title_from_uuid(dataset, u'(Unavailable)'),
                'layers': sorted(layers)
            } for dataset, layers in exp.environmental_datasets.items()
            ),
        })
    return details


def projection_listing_details(expbrain):

    # TODO: duplicate code here... see org.bccvl.site.browser.widget.py
    # TODO: generated list here not very useful,.... all layers over all sdms are concatenated
    # TODO: whata about future datasets?
    details = {}
    exp = expbrain.getObject()
    inputexps = set()
    futureenvs = set()
    for env_uuid in exp.future_climate_datasets:
        futureenvs.add(get_title_from_uuid(env_uuid, u'(Unavailable)'))

    for sdmuuid in exp.species_distribution_models:
        inputexps.add(get_title_from_uuid(sdmuuid, u'(Unavailable)'))
        sdmexp = uuidToObject(sdmuuid)
        if sdmexp is not None:
            # TODO: absence data
            envlayers = []
            # TODO: list all the subset layers??
            if sdmexp.portal_type == 'org.bccvl.content.mmexperiment':
                environmental_datasets = sdmexp.datasubsets[0].get('environmental_datasets')
            else:
                environmental_datasets = sdmexp.environmental_datasets
            for envuuid, layers in sorted(environmental_datasets.items()):
                envbrain = uuidToCatalogBrain(envuuid)
                envtitle = envbrain.Title if envbrain else u'Missing dataset'
                envlayers.append({
                    'title': envtitle,
                    'layers': sorted(layers)
                })
                # TODO: job_params has only id of function not uuid ... not sure how to get to the title
                toolkits = ', '.join(uuidToObject(sdmmodel).__parent__.job_params[
                                     'function'] for sdmmodel in exp.species_distribution_models[sdmuuid])
                if sdmexp.portal_type in ('org.bccvl.content.sdmexperiment', 'org.bccvl.content.mmexperiment'):
                    species_occ = get_title_from_uuid(sdmexp.species_occurrence_dataset,
                                                      u'(Unavailable)') if sdmexp.species_occurrence_dataset else ''
                else:
                    # not sdm,... probably msdm?
                    species_occ = get_title_from_uuid(sdmexp.species_occurrence_collections,
                                                      u'(Unavailable)') if sdmexp.species_occurrence_collections else ''
        else:
            toolkits = 'missing experiment'
            species_occ = ''
            envlayers = []

        details.update({
            'type': 'PROJECTION',
            'functions': toolkits,
            'species_occurrence': species_occ,
            'species_absence': '',
            'environmental_layers': envlayers,
            'input_experiments': inputexps,
            'future_env_datasets': futureenvs
        })
    return details


def biodiverse_listing_details(expbrain):
    details = {}
    exp = expbrain.getObject()
    species = set()
    years = set()
    months = set()
    emscs = set()
    gcms = set()
    inputexps = set()
    for expuuid, val in exp.projection.iteritems():
        inputexps.add(get_title_from_uuid(expuuid, u'(Unavailable)'))
        for dsuuid in val:
            dsobj = uuidToObject(dsuuid)
            # TODO: should inform user about missing dataset
            if dsobj:
                md = IBCCVLMetadata(dsobj)
                species.add(md.get('species', {}).get('scientificName', u'(Unavailable)'))
                year = md.get('year')
                if year:
                    years.add(year)
                month = md.get('month')
                if month:
                    months.add(month)
                gcm = md.get('gcm')
                if gcm:
                    gcms.add(gcm)
                emsc = md.get('emsc')
                if emsc:
                    emscs.add(emsc)
    details.update({
        'type': 'BIODIVERSE',
        'functions': 'endemism, redundancy',
        'species_occurrence': ', '.join(sorted(species)),
        'species_absence': '{}, {}'.format(', '.join(sorted(emscs)),
                                           ', '.join(sorted(gcms))),
        'years': ', '.join(sorted(years)),
        'months': ', '.join(sorted(months)),
        'input_experiments': inputexps
    })
    return details


def ensemble_listing_details(expbrain):
    # FIXME: implement this
    details = {}
    exp = expbrain.getObject()
    inputexps = set()
    for  sdmuuid in exp.datasets:
        inputexps.add(get_title_from_uuid(sdmuuid, u'(Unavailable)'))

    details.update({
        'type': 'ENSEMBLE',
        'functions': '',
        'species_occurrence': '',
        'species_absence': '',
        'environmental_layers': '',
        'input_experiments': inputexps
    })
    return details


def speciestraits_listing_details(expbrain):
    # FIXME: implement this
    exp = expbrain.getObject()
    species_occ = get_title_from_uuid(exp.species_traits_dataset,
                                      u'(Unavailable)') if exp.species_traits_dataset else ''

    toolkits_species = exp.algorithms_species or []
    toolkits_diff = exp.algorithms_diff or []
    toolkits = ', '.join(get_title_from_uuid(uuid, u'(Unavailable)') for uuid in
                         chain(toolkits_species, toolkits_diff) if uuid)

    envds = exp.environmental_datasets or {}
    envlayers = []
    for envuuid, layers in sorted(envds.items()):
        envbrain = uuidToCatalogBrain(envuuid)
        envtitle = envbrain.Title if envbrain else u'Missing dataset'
        envlayers.append({
            'title': envtitle,
            'layers': sorted(layers)
        })

    details = {}
    details.update({
        'type': 'STM',
        'functions': toolkits,
        'species_occurrence': species_occ,
        'species_absence': '',
        'environmental_layers': envlayers,
        'traits_dataset_params': exp.species_traits_dataset_params.items()
    })
    return details


def mme_listing_details(expbrain):
    details = {}
    exp = expbrain.getObject()
    if exp.datasubsets:
        subsets = []
        for subset in exp.datasubsets:
            subsetdata = subset.get('subset')
            if not subsetdata:
                continue
            title = subsetdata.get('title', u'missing data-subset') + ' - ' + ','.join(subsetdata.get('value'))
            envlayers = []
            for envuuid, layers in subset.get('environmental_datasets', {'': ['']}).items():
                envlayers.append({
                    'title': get_title_from_uuid(envuuid, u'(Unavailable)'),
                    'layers': sorted(layers)
                })
            subsets.append({'title': title, 'layers': envlayers})

        details.update({
            'type': 'MIGRATORY',
            'functions': get_title_from_uuid(exp.function, u'(Unavailable)'),
            'species_occurrence': get_title_from_uuid(
                exp.species_occurrence_dataset, u'(Unavailable)') if exp.species_occurrence_dataset else '',
            'species_absence': '',
            'environmental_layers': subsets
        })
    return details

