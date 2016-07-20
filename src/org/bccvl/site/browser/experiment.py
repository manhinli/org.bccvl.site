from collections import OrderedDict
from decimal import Decimal
from itertools import chain
import logging

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.statusmessages.interfaces import IStatusMessage
from plone import api
from plone.app.uuid.utils import uuidToCatalogBrain, uuidToObject
from plone.autoform.base import AutoFields
from plone.autoform.utils import processFields
from plone.dexterity.browser import add, edit, view
from plone.supermodel import loadString
from plone.z3cform.fieldsets.group import Group
from z3c.form import button
from z3c.form.form import extends  # , applyChanges  #, MultipleErrors
from z3c.form.interfaces import WidgetActionExecutionError, ActionExecutionError, IErrorViewSnippet, NO_VALUE, DISPLAY_MODE
from zope.component import getMultiAdapter
from zope.component import getUtility
from zope.interface import Invalid
from zope.schema.interfaces import IVocabularyFactory
from zope.schema.interfaces import RequiredMissing

from org.bccvl.site import MessageFactory as _
from org.bccvl.site.interfaces import IBCCVLMetadata
from org.bccvl.site.interfaces import IExperimentJobTracker
from org.bccvl.site.job.interfaces import IJobTracker
from org.bccvl.tasks.plone.jobs import submit_experiment
from org.bccvl.tasks.plone.utils import after_commit_task, create_task_context


LOG = logging.getLogger(__name__)


# FIXME: probably need an additional widget traverser to inline
#        validate param_groups fields
class ExperimentParamGroup(AutoFields, Group):

    parameters = None

    def getContent(self):
        if hasattr(self.context, 'parameters'):
            # TODO: do better check here?
            # add form context should not have any parameters field
            # edit form should have
            self.parameters = self.context.parameters
        if self.parameters is None:
            # TODO: check assumption here
            # assume that we have an add form and need a fresh dict?
            self.parameters = {}
        if not self.toolkit in self.parameters:
            self.parameters[self.toolkit] = {}
        return self.parameters[self.toolkit]

    def update(self):
        # FIXME: stupid autoform thinks if the schema is in schema
        #        attribute and not in additionalSchemata it won't need a
        #        prefix
        # self.updateFieldsFromSchemata()
        #
        # stupid autoform thinks self.groups should be a list and not a tuple :(
        self.groups = list(self.groups)
        # use  processFields instead
        processFields(self, self.schema, prefix=self.toolkit) #, permissionChecks=have_user)
        # revert back to tuple
        self.groups = tuple(self.groups)

        super(ExperimentParamGroup, self).update()


class ParamGroupMixin(object):
    """
    Mix-in to handle parameter froms
    """

    param_groups = ()

    def addToolkitFields(self):
        # FIXME: This relies on the order the vicabularies are returned, which shall be fixed.
        vocab = getUtility(IVocabularyFactory, "org.bccvl.site.algorithm_category_vocab")(self.context)
        groups = OrderedDict((cat.value,[]) for cat in vocab)

        # TODO: only sdms have functions at the moment ,... maybe sptraits as well?
        func_vocab = getUtility(IVocabularyFactory, name=self.func_vocab_name)
        functions = getattr(self.context, self.func_select_field, None) or ()

        # TODO: could also use uuidToObject(term.value) instead of relying on BrainsVocabluary terms
        for toolkit in (term.brain.getObject() for term in func_vocab(self.context)):
            if self.mode == DISPLAY_MODE and not self.is_toolkit_selected(toolkit.UID(), functions):
                # filter out unused algorithms in display mode
                continue
            # FIXME: need to cache form schema
            try:
                # FIXME: do some schema caching here
                parameters_model = loadString(toolkit.schema)
            except Exception as e:
                LOG.fatal("couldn't parse schema for %s: %s", toolkit.id, e)
                continue

            # Skip if algorithm does not have a category or unknown category
            if toolkit.algorithm_category is None or toolkit.algorithm_category not in groups:
                continue

            parameters_schema = parameters_model.schema

            param_group = ExperimentParamGroup(
                self.context,
                self.request,
                self)
            param_group.__name__ = "parameters_{}".format(toolkit.UID())
            #param_group.prefix = ''+ form.prefix?
            param_group.toolkit = toolkit.UID()
            param_group.schema = parameters_schema
            #param_group.prefix = "{}{}.".format(self.prefix, toolkit.id)
            #param_group.fields = Fields(parameters_schema, prefix=toolkit.id)
            param_group.label = u"configuration for {}".format(toolkit.title)
            if len(parameters_schema.names()) == 0:
                param_group.description = u"No configuration options"
            groups[toolkit.algorithm_category].append(param_group)

        # join the lists in that order
        self.param_groups = (tuple(groups['profile'])
                             + tuple(groups['machineLearning'])
                             + tuple(groups['statistical'])
                             + tuple(groups['geographic']))

    def updateFields(self):
        super(ParamGroupMixin, self).updateFields()
        self.addToolkitFields()

    def updateWidgets(self):
        super(ParamGroupMixin, self).updateWidgets()
        # update groups here
        for group in self.param_groups:
            try:
                group.update()
            except Exception as e:
                LOG.info("Group %s failed: %s", group.__name__, e)
        # should group generation happen here in updateFields or in update?

    def extractData(self, setErrors=True):
        data, errors = super(ParamGroupMixin, self).extractData(setErrors)
        for group in self.param_groups:
            groupData, groupErrors = group.extractData(setErrors=setErrors)
            data.update(groupData)
            if groupErrors:
                if errors:
                    errors += groupErrors
                else:
                    errors = groupErrors
        return data, errors

    def applyChanges(self, data):
        changed = super(ParamGroupMixin, self).applyChanges(data)
        # apply algo params:
        new_params = {}
        for group in self.param_groups:
            if self.is_toolkit_selected(group.toolkit, data[self.func_select_field]):
                group.applyChanges(data)
                new_params[group.toolkit] = group.getContent()
        self.context.parameters = new_params

        return changed


# DefaultEditView = layout.wrap_form(DefaultEditForm)
# from plone.z3cform import layout
class View(edit.DefaultEditForm):
    """
    View Experiment
    """

    # id = 'view'
    # enctype = None
    mode = DISPLAY_MODE

    extends(view.DefaultView)

    template = ViewPageTemplateFile("experiment_view.pt")

    label = ''

    def job_state(self):
        return IExperimentJobTracker(self.context).state

    # condition=lambda form: form.showApply)
    @button.buttonAndHandler(u'Start Job')
    def handleStartJob(self, action):
        data, errors = self.extractData()

        if errors:
            self.status = self.formErrorsMessage
            return

        # auto start job here
        context = create_task_context(self.context)
        context['experiment'] = {
            'title': self.context.title,
            'url': self.context.absolute_url()
        }
        after_commit_task(submit_experiment, context=context)
        jt = IJobTracker(self.context)
        job = jt.new_job('TODO: generate id',
                         'generate taskname: submit_experiment')
        job.type = self.context.portal_type
        jt.state = 'PENDING'
        jt.set_progress('PENDING'
                        u'submit experiment pending ')
        # TODO: need some job state here, so that user knows we are submitting jobs (currently depends on result folder job states)
        IStatusMessage(self.request).add('Job submitted {0}'.format(self.context.title), type='info')
        self.request.response.redirect(self.context.absolute_url())


class SDMView(ParamGroupMixin, View):
    """
    View SDM Experiment
    """
    # Parameters for ParamGroupMixin
    func_vocab_name = 'sdm_functions_source'
    func_select_field = 'functions'

    def is_toolkit_selected(self, tid, data):
        return tid in data


class Edit(edit.DefaultEditForm):
    """
    Edit Experiment
    """

    template = ViewPageTemplateFile("experiment_edit.pt")


class SDMEdit(ParamGroupMixin, Edit):
    """
    Edit SDM Experiment
    """
    # Parameters for ParamGroupMixin
    func_vocab_name = 'sdm_functions_source'
    func_select_field = 'functions'

    def is_toolkit_selected(self, tid, data):
        return tid in data


class Add(add.DefaultAddForm):
    """
    Add Experiment
    """

    template = ViewPageTemplateFile("experiment_add.pt")

    extends(view.DefaultView,
            ignoreButtons=True)

    buttons = button.Buttons(add.DefaultAddForm.buttons['cancel'])

    @button.buttonAndHandler(_('Create and start'), name='save')
    def handleAdd(self, action):
        data, errors = self.extractData()
        self.validateAction(data)
        if errors:
            self.status = self.formErrorsMessage
            return
        # TODO: this is prob. a bug in base form, because createAndAdd
        #       does not return the wrapped object.
        obj = self.createAndAdd(data)
        if obj is None:
            # TODO: this is probably an error here?
            #       object creation/add failed for some reason
            return
        # get wrapped instance fo new object (see above)
        obj = self.context[obj.id]
        # mark only as finished if we get the new object
        self._finishedAdd = True
        IStatusMessage(self.request).addStatusMessage(_(u"Item created"),
                                                      "info")
        # auto start job here
        context = create_task_context(obj)
        context['experiment'] = {
            'title': obj.title,
            'url': obj.absolute_url()
        }
        after_commit_task(submit_experiment, context=context)

        # Create a submission job tracker for the experiment
        jt = IJobTracker(obj) 
        job = jt.new_job('TODO: generate id',
                 'generate taskname: submit_experiment')
        job.type = self.context.portal_type
        jt.state = 'PENDING'
        jt.set_progress('PENDING', u'submit experiment pending ')

        # TODO: need some job state here, so that user knows we are submitting jobs (currently depends on result folder job states)
        IStatusMessage(self.request).add('Job submitted {0}'.format(obj.title), type='info')

    @button.buttonAndHandler(_('Create'), name='create')
    def handleCreate(self, action):
        data, errors = self.extractData()
        self.validateAction(data)
        if errors:
            self.status = self.formErrorsMessage
            return
        # TODO: this is prob. a bug in base form, because createAndAdd
        #       does not return the wrapped object.
        obj = self.createAndAdd(data)
        if obj is None:
            # TODO: this is probably an error here?
            #       object creation/add failed for some reason
            return
        # get wrapped instance fo new object (see above)
        obj = self.context[obj.id]
        # mark only as finished if we get the new object
        self._finishedAdd = True
        IStatusMessage(self.request).addStatusMessage(_(u"Item created"),
                                                      "info")


class SDMAdd(ParamGroupMixin, Add):
    """
    Add SDM Experiment
    """

    portal_type = "org.bccvl.content.sdmexperiment"

    # Parameters for ParamGroupMixin
    func_vocab_name = 'sdm_functions_source'
    func_select_field = 'functions'

    def is_toolkit_selected(self, tid, data):
        return tid in data

    def create(self, data):
        # Dexterity base AddForm bypasses self.applyData and uses form.applyData directly,
        # we'll have to override it to find a place to apply our algo_group data'
        newob = super(SDMAdd, self).create(data)
        # apply values to algo dict manually to make sure we don't write data on read
        new_params = {}
        for group in self.param_groups:
            if group.toolkit in data['functions']:
                group.applyChanges(data)
                new_params[group.toolkit] = group.getContent()
        newob.parameters = new_params
        IBCCVLMetadata(newob)['resolution'] = data['resolution']
        return newob

    def validateAction(self, data):
        # ActionExecutionError ... form wide error
        # WidgetActionExecutionError ... widget specific
        # TODO: validate all sort of extra info- new object does not exist yet
        # data contains already field values
        datasets = data.get('environmental_datasets', {}).keys()
        if not datasets:
            # FIXME: Make this a widget error, currently shown as form wide error
            raise ActionExecutionError(Invalid('No environmental dataset selected.'))

        # Determine highest resolution
        # FIXME: this is slow and needs improvements
        #        and accessing _terms is not ideal
        res_vocab = getUtility(IVocabularyFactory, 'resolution_source')(self.context)
        if data.get('scale_down', False):
            # ... find highest resolution
            resolution_idx = 99 # Arbitrary choice of upper index limit
            for dsbrain in (uuidToCatalogBrain(d) for d in datasets):
                idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.BCCResolution))
                if idx < resolution_idx:
                    resolution_idx = idx
            data['resolution'] = res_vocab._terms[resolution_idx].value
        else:
            # ... find lowest resolution
            resolution_idx = -1
            for dsbrain in (uuidToCatalogBrain(d) for d in datasets):
                idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.BCCResolution))
                if idx > resolution_idx:
                    resolution_idx = idx
            data['resolution'] = res_vocab._terms[resolution_idx].value


class MSDMAdd(ParamGroupMixin, Add):
    """
    Add MSDM Experiment
    """

    portal_type = "org.bccvl.content.msdmexperiment"

    # Parameters for ParamGroupMixin
    func_vocab_name = 'sdm_functions_source'
    func_select_field = 'functions'

    def is_toolkit_selected(self, tid, data):
        return tid in data

    def create(self, data):
        # Dexterity base AddForm bypasses self.applyData and uses form.applyData directly,
        # we'll have to override it to find a place to apply our algo_group data'
        newob = super(MSDMAdd, self).create(data)
        # apply values to algo dict manually to make sure we don't write data on read
        new_params = {}
        for group in self.param_groups:
            if group.toolkit == data['function']:
                group.applyChanges(data)
                new_params[group.toolkit] = group.getContent()
        newob.parameters = new_params
        IBCCVLMetadata(newob)['resolution'] = data['resolution']
        return newob

    def validateAction(self, data):
        # ActionExecutionError ... form wide error
        # WidgetActionExecutionError ... widget specific
        # TODO: validate all sort of extra info- new object does not exist yet
        # data contains already field values
        datasets = data.get('environmental_datasets', {}).keys()
        if not datasets:
            # FIXME: Make this a widget error, currently shown as form wide error
            raise ActionExecutionError(Invalid('No environmental dataset selected.'))

        # Determine highest resolution
        # FIXME: this is slow and needs improvements
        #        and accessing _terms is not ideal
        res_vocab = getUtility(IVocabularyFactory, 'resolution_source')(self.context)
        if data.get('scale_down', False):
            # ... find highest resolution
            resolution_idx = 99 # Arbitrary choice of upper index limit
            for dsbrain in (uuidToCatalogBrain(d) for d in datasets):
                idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.BCCResolution))
                if idx < resolution_idx:
                    resolution_idx = idx
            data['resolution'] = res_vocab._terms[resolution_idx].value
        else:
            # ... find lowest resolution
            resolution_idx = -1
            for dsbrain in (uuidToCatalogBrain(d) for d in datasets):
                idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.BCCResolution))
                if idx > resolution_idx:
                    resolution_idx = idx
            data['resolution'] = res_vocab._terms[resolution_idx].value


class ProjectionAdd(Add):

    portal_type = 'org.bccvl.content.projectionexperiment'

    def create(self, data):
        newob = super(ProjectionAdd, self).create(data)
        # store resolution determined during validateAction
        IBCCVLMetadata(newob)['resolution'] = data['resolution']
        return newob

    def validateAction(self, data):
        """
        Get resolution from SDM and use it to find future datasets

        TODO: if required layers are not available in future datasets, use current layers from SDM
        """
        # ActionExecutionError ... form wide error
        # WidgetActionExecutionError ... widget specific

        # TODO: match result layers with sdm layers and get missing layers from SDM?
        #       -> only environmental? or missing climate layers as well?
        #       do matching here? or in job submit?

        datasets = data.get('future_climate_datasets', [])
        if not datasets:
            # FIXME: Make this a widget error, currently shown as form wide error
            raise ActionExecutionError(Invalid('No future climate dataset selected.'))
        models = data.get('species_distribution_models', {})
        if not tuple(chain.from_iterable(x for x in models.values())):
            # FIXME: collecting all errors is better than raising an exception for each single error
            # TODO: see http://stackoverflow.com/questions/13040487/how-to-raise-a-widgetactionexecutionerror-for-multiple-fields-with-z3cform
            raise WidgetActionExecutionError(
                'species_distribution_models',
                Invalid('No source dataset selected.')
            )

        # Determine lowest resolution
        # FIXME: this is slow and needs improvements
        #        and accessing _terms is not ideal
        res_vocab = getUtility(IVocabularyFactory, 'resolution_source')(self.context)
        resolution_idx = -1
        for dsbrain in (uuidToCatalogBrain(d) for d in datasets):
            idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.BCCResolution))
            if idx > resolution_idx:
                resolution_idx = idx
        data['resolution'] = res_vocab._terms[resolution_idx].value


class BiodiverseAdd(Add):

    portal_type = "org.bccvl.content.biodiverseexperiment"

    def validateAction(self, data):
        # TODO: check data ...
        # ...
        datasets = data.get('projection', {})
        if not tuple(chain.from_iterable(x for x in datasets.values())):
            raise WidgetActionExecutionError(
                'projection',
                Invalid('No projection dataset selected.')
            )
        # check if threshold values are in range
        for dataset in (x for x in datasets.values()):
            if not dataset:
                raise WidgetActionExecutionError(
                    'projection',
                    Invalid('Please select at least one dataset within experiment'))
            # key: {label, value}
            dsuuid = dataset.keys()[0]
            ds = uuidToObject(dsuuid)
            value = dataset[dsuuid]['value']
            md = IBCCVLMetadata(ds)
            # ds should be a projection output which has only one layer
            # FIXME: error message is not clear enough and
            #        use widget.errors instead of exception
            #        also it will only verify if dateset has min/max values in metadata
            layermd = md['layers'].values()[0]
            if 'min' in layermd and 'max' in layermd:
                # FIXME: at least layermd['min'] may be a string '0', when comparing to decimal from threshold selector, this comparison fails and raises the widget validation error
                if value <= float(layermd['min']) or value >= float(layermd['max']):
                    raise WidgetActionExecutionError(
                        'projection',
                        Invalid('Selected threshold is out of range'))


class EnsembleAdd(Add):

    portal_type = "org.bccvl.content.ensemble"

    def create(self, data):
        newob = super(EnsembleAdd, self).create(data)
        # store resolution determined during validateAction
        IBCCVLMetadata(newob)['resolution'] = data['resolution']
        return newob

    def validateAction(self, data):
        datasets = list(chain.from_iterable(data.get('datasets', {}).values()))
        if not datasets:
            # FIXME: Make this a widget error, currently shown as form wide error
            raise ActionExecutionError(Invalid('No dataset selected.'))

        # all selected datasets are combined into one ensemble analysis
        # get resolution for ensembling
        # Determine lowest resolution
        # FIXME: An experiment should store the resolution metadata on the dataset
        #        e.g. an SDM current projection needs to store resolution on tif file
        res_vocab = getUtility(IVocabularyFactory, 'resolution_source')(self.context)
        resolution_idx = -1
        for dsbrain in (uuidToCatalogBrain(d) for d in datasets):
            try:
                idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.BCCResolution))
            except:
                # FIXME: need faster way to order resolutions
                idx = res_vocab._terms.index(res_vocab.getTerm(dsbrain.getObject().__parent__.job_params['resolution']))
            if idx > resolution_idx:
                resolution_idx = idx
        data['resolution'] = res_vocab._terms[resolution_idx].value


class SpeciesTraitsView(ParamGroupMixin, View):
    """
    View SDM Experiment
    """
    # Parameters for ParamGroupMixin
    func_vocab_name = 'traits_functions_source'
    func_select_field = 'algorithm'

    # override is_toolkit_selected
    def is_toolkit_selected(self, tid, data):
        return tid == data


class SpeciesTraitsEdit(ParamGroupMixin, Edit):
    """
    Edit SDM Experiment
    """
    # Parameters for ParamGroupMixin
    func_vocab_name = 'traits_functions_source'
    func_select_field = 'algorithm'

    # override is_toolkit_selected
    def is_toolkit_selected(self, tid, data):
        return tid == data


class SpeciesTraitsAdd(ParamGroupMixin, Add):

    portal_type = "org.bccvl.content.speciestraitsexperiment"

    # Parameters for ParamGroupMixin
    func_vocab_name = 'traits_functions_source'
    func_select_field = 'algorithm'

    # override is_toolkit_selected
    def is_toolkit_selected(self, tid, data):
        return tid == data

    def create(self, data):
        # Dexterity base AddForm bypasses self.applyData and uses form.applyData directly,
        # we'll have to override it to find a place to apply our algo_group data'
        newob = super(SpeciesTraitsAdd, self).create(data)
        # apply values to algo dict manually to make sure we don't write data on read
        new_params = {}
        for group in self.param_groups:
            if group.toolkit == data['algorithm']:
                group.applyChanges(data)
                new_params[group.toolkit] = group.getContent()
        newob.parameters = new_params
        return newob

    def validateAction(self, data):
        # TODO: check data ...
        pass
