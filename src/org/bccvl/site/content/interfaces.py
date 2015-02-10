from zope.interface import Interface
from plone.directives import form
from plone.namedfile.field import NamedBlobFile
from plone.app.textfield import RichText as RichTextField
from zope.schema import Choice, List, Dict, Bool, Int, TextLine, Text, Set
from z3c.form.browser.checkbox import CheckBoxFieldWidget
from z3c.form.browser.radio import RadioFieldWidget
from org.bccvl.site import MessageFactory as _
# next import may cause circular import problems
from org.bccvl.site.widgets.widgets import DatasetFieldWidget
from org.bccvl.site.widgets.widgets import DatasetLayersFieldWidget
from org.bccvl.site.widgets.widgets import ExperimentSDMFieldWidget
from org.bccvl.site.widgets.widgets import FutureDatasetsFieldWidget


class IDataset(form.Schema):
    """Interface all datasets inherit from"""

    rightsstatement = RichTextField(
        title=u'Rights Statement',
        description=u"",
        required=False,
    )


class IBlobDataset(IDataset):

    # TODO: a primary field should not be required. possible bug in plone core
    form.primary('file')
    file = NamedBlobFile(
        title=_(u"File"),
        description=_(u"Data content"),
        required=True
    )


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

    form.widget(functions=CheckBoxFieldWidget)
    functions = List(
        title=u'Algorithm',
        value_type=Choice(vocabulary='sdm_functions_source'),
        default=None,
        required=True,
    )

    form.widget('species_occurrence_dataset',
                DatasetFieldWidget,
                genre=['DataGenreSpeciesOccurrence'],
                errmsg=u"Please select at least 1 occurrence dataset.",
                vizclass=u'fine bccvl-occurrence-viz')
    species_occurrence_dataset = TextLine(
        title=u'Species Occurrence Datasets',
        default=None,
        required=True,
    )

    form.widget('species_absence_dataset',
                DatasetFieldWidget,
                genre=['DataGenreSpeciesAbsence'],
                errmsg=u"Please select at least 1 emmission scenario.",
                vizclass=u'fine bccvl-absence-viz')
    species_absence_dataset = TextLine(
        title=u'Species Absence Datasets',
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

    form.widget('environmental_datasets',
                DatasetLayersFieldWidget,
                genre=['DataGenreCC', 'DataGenreE'],
                errmsg=u"Please select at least 1 layer.")
    environmental_datasets = Dict(
        title=u'Climate & Environmental Datasets',
        key_type=TextLine(),
        value_type=Set(value_type=TextLine()),
        required=True,
    )


class IProjectionExperiment(IExperiment):

    # TODO: ignore context here? don't really need to store this?
    form.widget('species_distribution_models',
                ExperimentSDMFieldWidget,
                errmsg=u"Please select at least 1 Species Distribution Model")
    species_distribution_models = Dict(
        title=u'Species Distribution Models',
        key_type=TextLine(),
        value_type=List(value_type=TextLine(), required=True),
        default=None,
        required=True,
    )

    form.widget('future_climate_datasets',
                FutureDatasetsFieldWidget,
                genre=['DataGenreFC'],
                errmsg=u"Please select at least 1 future climate dataset.",
                vizclass=u'fine bccvl-absence-viz')
    future_climate_datasets = List(
        title=u'Future Climate Data',
        value_type=TextLine(),
        default=None,
        required=True
    )


class IBiodiverseExperiment(IExperiment):

    resolution = Choice(
        title=u'Resolution',
        default=None,
        vocabulary='resolution_source',
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

    # datasets =

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
                DatasetFieldWidget,
                errmsg=u"Please select at least 1 emmission scenario.",
                genre=['DataGenreTraits'],
                vizclass=u'fine bccvl-auto-viz')
    data_table = Choice(
        title=u'Dataset',
        vocabulary='species_traits_datasets_vocab',
        default=None,
        required=True,
    )
