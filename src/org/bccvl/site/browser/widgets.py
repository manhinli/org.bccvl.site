from zope.component import adapter, getMultiAdapter, getUtility
from zope.interface import implementer, alsoProvides
from zope.schema.interfaces import ISequence, ITitledTokenizedTerm, IContextSourceBinder
from z3c.form import util
from z3c.form.interfaces import (IFieldWidget,  IFormLayer,
                                 ITerms, IFormAware, NO_VALUE)
from z3c.form.widget import FieldWidget, Widget, SequenceWidget
from z3c.form.browser.orderedselect import OrderedSelectWidget
from z3c.form.browser.widget import (HTMLFormElement, HTMLInputWidget,
                                     addFieldClass)
from zope.i18n import translate
from .interfaces import (IDatasetsWidget, IDatasetsRadioWidget,
                         IOrderedCheckboxWidget)
from Products.CMFCore.utils import getToolByName
from plone.app.uuid.utils import uuidToCatalogBrain


@implementer(IOrderedCheckboxWidget)
class OrderedCheckboxWidget(OrderedSelectWidget):
    """
    Class that implements IOrderedCheckboxWidget
    """


@adapter(ISequence,  IFormLayer)
@implementer(IFieldWidget)
def SequenceCheckboxFieldWidget(field,  request):
    """
    FieldWidget that uses OrderedCheckboxWidget
    """
    return FieldWidget(field,  OrderedCheckboxWidget(request))


@implementer(IDatasetsWidget)
class DatasetsWidget(HTMLFormElement, Widget):
    """
    render a list of checkboxes for keys in dictionary.
    render a default widget for values per key
    """
    # TODO: assumes that values are independent of keys for now.

    items = ()

    @property
    def markerName(self):
        return "{}.marker".format(self.name)

    @property
    def marker(self):
        return '<input type="hidden" name="{}" value="1"/>'.format(
            self.markerName)

    def getValueWidget(self, token, value, prefix=None):
        valueType = getattr(self.field, 'value_type')
        widget = getMultiAdapter((valueType, self.request),
                                 IFieldWidget)
        self.setValueWidgetName(widget, token, prefix)
        widget.mode = self.mode
        if IFormAware.providedBy(self):
            widget.form = self.form
            alsoProvides(widget, IFormAware)
        # TODO: is this the wrong way round? shouldn't I update first
        #       and the set the value? For some reason the OrderedSelect
        #       needs to know the value before it updates
        #       As it is now, the widget might re-set the value from request
        if self.value and value in self.value:
            widget.value = self.value[value]
        widget.update()
        return widget

    def setValueWidgetName(self, widget, idx, prefix=None):
        names = lambda id: [str(n) for n in [id]+[prefix, idx]
                            if n is not None]
        widget.name = '.'.join([str(self.name)]+names(None))
        widget.id = '-'.join([str(self.id)]+names(None))

    def getItem(self, term):
        id = '{}-{}'.format(self.id, term.token)
        name = '{}.{}'.format(self.name, term.token)
        if ITitledTokenizedTerm.providedBy(term):
            content = term.title
        else:
            content = term.value
        value_widget = self.getValueWidget(term.token, term.value)
        return {'id': id, 'name': name,
                'token': term.token,
                'value': term.token, 'content': content,
                'checked': self.value and term.token in self.value,
                'value_widget': value_widget}

    def update(self):
        super(DatasetsWidget, self).update()
        addFieldClass(self)
        keyterms = getMultiAdapter(
            (self.context, self.request, self.form, self.field.key_type, self),
            ITerms)

        self.items = [
            self.getItem(term)
            for term in keyterms]

    def extract(self):
        # extract the value for the widget from the request and return
        # a tuple of (key,value) pairs

        # check marker so that we know if we have a request to look at or
        # whether we should check for values from current context
        if not self.markerName in self.request:
            return NO_VALUE
        values = []
        for item in self.items:
            cbname = '{}.select'.format(item['name'])
            if cbname in self.request:
                value_widget = self.getValueWidget(item['token'], item['value'])
                values.append((item['value'], value_widget.value))
        return dict(values)


def DatasetsFieldWidget(field, request):
    """
    Widget to select datasets and layers
    """
    return FieldWidget(field,  DatasetsWidget(request))


@implementer(IDatasetsRadioWidget)
class DatasetsRadioWidget(HTMLInputWidget, SequenceWidget):

    klass = u'radio-widget'
    css = u'radio'

    def isChecked(self, term):
        return term.token in self.value

    @property
    def items(self):
        # TODO: could this be a generator?
        items = []
        for count, term in enumerate(self.terms):
            checked = self.isChecked(term)
            id = '%s-%i' % (self.id, count)
            if ITitledTokenizedTerm.providedBy(term):
                label = translate(term.title, context=self.request,
                                  default=term.title)
            else:
                label = util.toUnicode(term.value)
            # do catalog query for additional infos
            items.append(
                {'id':id, 'name':self.name, 'value':term.token,
                 'label':label, 'checked':checked})
        return items

    def get_item_details(self, item):
        # TODO: code duplication see: experiments_listing_view.py:45
        # TODO: fetch additional data for item here
        pc = getToolByName(self.context, 'portal_catalog')
        brain = pc.searchResults(UID=item['value'])[0]
        sdm = brain.getObject()
        # TODO: we might have two options here
        #       sdm could be uploaded, then we'll show other data
        #       for now ignore this case and consider only results for sdm experiments
        result = sdm.__parent__
        exp = result.__parent__
        occurbrain = uuidToCatalogBrain(exp.species_occurrence_dataset)
        #TODO:  need function for this specific str
        envlayervocab = getUtility(IContextSourceBinder, name='envirolayer_source')(self.context)
        # TODO: absence data
        envlayers = ', '.join(
                '{}: {}'.format(uuidToCatalogBrain(envuuid).Title,
                                ', '.join(envlayervocab.getTerm(envlayer).title
                                          for envlayer in sorted(layers)))
                    for (envuuid, layers) in sorted(exp.environmental_datasets.items()))

        return {
            'model': brain,
            'experiment': exp,
            'function': result.toolkit,
            'species': occurbrain,
            'layers': envlayers
        }

    def update(self):
        super(DatasetsRadioWidget, self).update()
        addFieldClass(self)


def DatasetsRadioFieldWidget(field, request):
    return FieldWidget(field, DatasetsRadioWidget(request))
