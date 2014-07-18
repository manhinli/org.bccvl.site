from zope.interface import Interface
from plone.directives import form
from plone.namedfile.field import NamedBlobFile
from zope.schema import Choice, List, Dict, Bool, Int, TextLine, Text
from z3c.form.browser.checkbox import CheckBoxFieldWidget
from z3c.form.browser.radio import RadioFieldWidget
from org.bccvl.site import MessageFactory as _
# next import may cause circular import problems
from org.bccvl.site.browser.widgets import SequenceCheckboxFieldWidget, DatasetsRadioFieldWidget
from org.bccvl.site.browser.converter import DatasetLayersField


class IDataset(form.Schema):
    """Interface all datasets inherit from"""


class IBlobDataset(IDataset):

    # TODO: a primary field should not be required. possible bug in plone core
    form.primary('file')
    file = NamedBlobFile(
        title=_(u"File"),
        description=_(u"Data content"),
        required=True
    )

    form.omitted('thresholds')
    thresholds = Dict(
        title=_(u"Thresholds"),
        default=None,
        required=False
    )

    # fixed fields
    # RDFURIChoiceField(
    #     __name__='format',
    #     prop=BCCPROP['format'],
    #     required=False,
    #     title=u'Format',
    #     vocabulary=u'http://namespaces.zope.org/z3c/form#DataSetFormatVocabulary')

    # layer
    # RDFURIChoiceField(
    #     __name__='datatype',
    #     prop=BCCPROP['datatype'],
    #     required=False,
    #     title=u'Type of Dataset',
    #     vocabulary=u'http://namespaces.zope.org/z3c/form#DataSetTypeVocabulary'),
    # # not needed?
    # RDFLiteralLineField(
    #     __name__='formato',
    #     prop=DCTERMS['format'],
    #     required=False,
    #     title=u'Data format (other)'),


class IRemoteDataset(IDataset):
    """A dateset hosted externally"""

    remoteUrl = TextLine(
        title=_(u'Content location'),
        description=u'',
        required=True,
        default=u'http://',
    )


class IExperiment(Interface):
    """Base Experiment Class"""


class ISDMExperiment(IExperiment):

    resolution = Choice(
        title=u'Resolution',
        default=None,
        vocabulary='org.bccvl.site.ResolutionVocabulary',
        required=True,
    )

    form.widget(functions=CheckBoxFieldWidget)
    functions = List(
        title=u'Algorithm',
        value_type=Choice(vocabulary='sdm_functions_source'),
        default=None,
        required=True,
    )

    form.widget('species_occurrence_dataset',
                DatasetsRadioFieldWidget,
                errmsg=u"Please select at least 1 emmission scenario.",
                vizclass=u'fine bccvl-occurrence-viz')
    species_occurrence_dataset = Choice(
        title=u'Species Occurrence Datasets',
        vocabulary='species_presence_datasets_vocab',
        default=None,
        required=False,
    )

    form.widget('species_absence_dataset',
                DatasetsRadioFieldWidget,
                errmsg=u"Please select at least 1 emmission scenario.",
                vizclass=u'fine bccvl-absence-viz')
    species_absence_dataset = Choice(
        title=u'Species Absence Datasets',
        source='species_absence_datasets_vocab',
        default=None,
        required=False,
    )

    species_pseudo_absence_points = Bool(
        title=u"Pseudo absence points",
        description=u"Enable generation of random pseudo absence "
                    u"points across area defined in environmental data",
        default=False,
        required=False)

    species_number_pseudo_absence_points = Int(
        title=u"Number of pseudo absence points",
        description=u"The number of random pseudo absence points to generate",
        default=10000,
        required=False)

    # store dataset + layer (or file within zip)
    # e.g. ... basic key and value_types .... and widget does heavy work?
    # FIXME: would be best if widget supplies only possible values (at least for key_type)
    form.widget(environmental_datasets='org.bccvl.site.browser.widgets.DatasetLayersFieldWidget')
    environmental_datasets = DatasetLayersField(
        title=u'Environmental Datasets',
        key_type=Choice(vocabulary='environmental_datasets_vocab'),
        value_type=List(Choice(vocabulary='envirolayer_source'),
                        unique=False),
        required=True,
    )


class IProjectionExperiment(IExperiment):

    # FIXME: this field is not required, until UI supports it
    resolution = Choice(
        title=u'Resolution',
        default=None,
        vocabulary='org.bccvl.site.ResolutionVocabulary',
        required=False,
    )

    form.widget(species_distribution_models=
                'org.bccvl.site.browser.widgets.DatasetsMultiSelectFieldWidget')
    species_distribution_models = List(
        title=u'Species Distribution Models',
        value_type=Choice(vocabulary='species_distributions_models_vocab'),
        default=None,
        required=True,
    )

    # TODO: instead of form hints ... maybe set widgetfactory in form
    #       updateWidgets?  form hint affects all forms ... using
    #       updateWidgets would require to customise every form where
    #       we want a custom widget
    # TODO: could add parsley-attributes to the widget here
    form.widget('years',
                SequenceCheckboxFieldWidget,
                errmsg=u"Please select at least 1 year.")
    years = List(
        title=u'Years',
        value_type=Choice(source='fc_years_source'),
        default=None,
        required=True,
    )

    form.widget('emission_scenarios',
                SequenceCheckboxFieldWidget,
                errmsg=u"Please select at least 1 emmission scenario.")
    emission_scenarios = List(
        title=u'Emission Scenarios',
        value_type=Choice(vocabulary='emission_scenarios_source'),
        default=None,
        required=True,
    )

    form.widget('climate_models',
                SequenceCheckboxFieldWidget,
                errmsg=u"Please select at least 1 climate model.")
    climate_models = List(
        title=u'Climate Models',
        value_type=Choice(source='global_climate_models_source'),
        default=None,
        required=True,
    )


class IBiodiverseExperiment(IExperiment):

    resolution = Choice(
        title=u'Resolution',
        default=None,
        vocabulary='org.bccvl.site.ResolutionVocabulary',
        required=False,
    )

    # options: use dicts or other things here
    #          number of items in both lists must match
    # FIXME: this list will store a list of datests + threshold values
    #        I don't have yet a widget for it so I can't add it to the interface'
    # projection = List(
    #     title=u'Projection Datasets',
    #     default=None,
    #     required=True,
    #     )

    cluster_size = Choice(
        title=u'Cluster size',
        description=u'x/y cell size in meter',
        default=5000,
        required=True,
        values=(5000, 10000, 20000, 50000),
    )

    # ->  interface,  content class? , profile,  add / edit / display / result view
    # ->  perl script ... exec env
    # =>  species metadata filenaming


class IEnsembleExperiment(IExperiment):

    pass


class ISpeciesTraitsExperiment(IExperiment):

    form.widget(algorithm=RadioFieldWidget)
    algorithm = Choice(
        title=u'Algorithm',
        vocabulary='traits_functions_source',
        required=True,
        default=None,
    )

    formula = Text(
        title=u'Formula',
        description=u'Please see <a href="http://stat.ethz.ch/R-manual/R-devel/library/stats/html/lm.htm">R:Fitting Linear Models</a> for details.',
        required=True,
        default=None,
    )

    form.widget('data_table',
                DatasetsRadioFieldWidget,
                errmsg=u"Please select at least 1 data set.",
                vizclass=u'fine bccvl-auto-viz')
    data_table = Choice(
        title=u'Dataset',
        vocabulary='species_traits_datasets_vocab',
        default=None,
        required=True,
    )
