from django import forms
from django.forms.widgets import HiddenInput
from .models import DataImport
from django.forms import modelformset_factory
from mediaset.shop.catalogue.models import Product


class DataImportForm(forms.ModelForm):
    class Meta:
        model = DataImport
        fields = ('upload',)


class DataImportAllForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['name'] = 'new_import_all'
        self.fields['name'].widget = HiddenInput()

    class Meta:
        model = DataImport
        fields = ('name', 'upload')


class ProductListForm(forms.ModelForm):
    # def __init__(self, *args, **kwargs):
    #     self.filter_price = kwargs.get('new')
    #     super(ProductListForm, self).__init__(*args, **kwargs)

    class Meta:
        model = Product
        # fields = ['name', 'code', 'category']
        fields = ('active',)


BaseProductFormSet = modelformset_factory(Product, form=ProductListForm, extra=0)


class ProductFormSet(BaseProductFormSet):
    pass