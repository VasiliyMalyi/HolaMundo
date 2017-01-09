import csv
import time
import datetime
import pyexcel
import django_excel as excel
from decimal import Decimal
from collections import OrderedDict

from django.shortcuts import render
from django.core.urlresolvers import reverse
from django.views.generic import FormView, UpdateView, ListView, CreateView, TemplateView, DetailView
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from mediaset.shop.catalogue.models import (
    Product, Category, ProductRecommendation, Manufacturer, ProductImage,
    SpecialProposition, Parameter, ParameterRange, PreFilter, PreFilterParameter,
    NewProductParameterValue, NewParameter, NewCategoryParameter, NewParameterValue)
from mediaset.shop.stock.models import StockRecord
from mediaset.dashboard.transfer.forms import DataImportForm
from mediaset.dashboard.transfer.models import DataImport, ProductPricesTransfer
from mediaset.dashboard.mixins import BulkEditMixin, CreateUrlMixin
from mediaset.dashboard.transfer.forms import ProductFormSet
from core.formset import PaginationModelFormSetView

class ImportDataView(ListView):
    model = Product
    template_name = 'dashboard/transfer/import_data.html'
    fields = ['name']
    context_object_name = 'products'
    product_formset = ProductFormSet
    from_form = ''
    upload_data = {}
    post_data = {}

    def get(self, request, *args, **kwargs):
        self.from_form = dict(request.GET)
        return super().get(request, *args, **kwargs)

    def get_accord(self, data):
        if data:
            accord_dict = OrderedDict(zip(data['pi'], data['pp']))
            return accord_dict

    def get_validation(self, data):
        for k, v in data.items():
            # try:
            #     category = Category.objects.get(name=k)
            # except Exception:
            #     raise Http404('Категории {} не существует'.format(k))
            if v[0] != ['name', 'code', 'price']:
                raise Http404('Некорректные названия колонок. Убедитесь, что всего 3 колонки и их названия: name, code, price')
            for i in v[1:]:
                try:
                    product = Product.objects.get(code=i[1])
                except Exception:
                    raise Http404('Товара с кодом {} не существует'.format(i[1]))
                if product.category.name != k:
                    raise Http404('В категории {} не существует товара с кодом {}'.format(k, i[1]))
                try:
                    price = float(i[2])
                except Exception:
                    raise Http404('Товар с кодом {} имеет неверный формат цены'.format(i[1]))
            code_list = [j[1] for j in v[1:]]
            dublicate_list = set([x for x in code_list if code_list.count(x) > 1])
            if dublicate_list:
                raise Http404('Обнаружено дублирование товаров с кодом: {}'.format(', '.join(dublicate_list)))
        return data

    def get_queryset(self):
        products = super().get_queryset()
        self.upload_data = self.get_accord(self.from_form)
        if self.upload_data:
            products = products.filter(code__in=list(self.upload_data.keys()))
            products_codes = [k for k, v in self.upload_data.items()
                              if StockRecord.objects.get(product=products.get(code=k).id).price != Decimal(v)]
            selected_products = products.filter(code__in=products_codes)
            return selected_products

    # from dashboard/catalogue/view.py --- start
    def post(self, request, *args, **kwargs):
        self.post_data = dict(request.POST)
        if not self.post_data:
            raise ValueError('No POST data')

        if 'item' in self.post_data.keys():
            d = dict(zip(self.post_data['item'], self.post_data['new']))
            products_records = StockRecord.objects.filter(product__code__in=d.keys())
            for product_record in products_records:
                for k, v in d.items():
                    if product_record.product.code == k:
                        product_record.price = v
                        product_record.save()
        else:
            self.from_form = self.post_data

        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))

    def all_formset_valid(self, product_formset):
        product_formset.save()
        return HttpResponseRedirect(self.get_success_url())

    def all_formset_invalid(self, product_formset):
        ctx = {
            'product_formset': product_formset,
        }
        return self.render_to_response(self.get_context_data(**ctx))
    # from dashboard/catalogue/view.py --- end

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if not self.from_form:
            f = DataImport.objects.latest('id')
            f = f.upload
            try:
                data = pyexcel.get_book_dict(file_type='xlsx', file_content=f.read())
            except Exception:
                raise Http404('Некорректный загружаемый файл')
            data = self.get_validation(data)
        else:
            data = {}

        if self.upload_data:
            new_prices = {}
            for product in self.get_queryset():
                for k, v in self.upload_data.items():
                    if product.code == k:
                        new_prices.update({product: v})
        else:
            new_prices = {}
        ctx['product_formset'] = self.product_formset(queryset=self.get_queryset())
        ctx_update = {
            'data_import': dict(data),
            'from_form': self.from_form,
            'test': self.get_queryset(),
            'new_prices': new_prices,
            'post_data': self.post_data,
            'get_accord': self.get_accord(self.from_form),
            'get_queryset': self.get_queryset()
        }

        ctx.update(ctx_update)

        return ctx

# second view

def export_products_view(request):
# Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename="somefilename.xlsx"'
    writer = csv.writer(response)

    start = time.time() # profiling

    if "export_prices" in request.GET:
        writer.writerow(['name', 'code', 'filter_price'])
        for item in Product.objects.all():
            writer.writerow([item.name, item.code, item.filter_price])
        writer.writerow(["Write all data", time.time() - start]) # profiling
        # writer.writerow(['Second row', 'A', 'B', 'C', '"Testing"', "Here's a quote"])
    elif "export_all" in request.GET:
        related_field_names = [f.name for f in Product._meta.get_all_related_objects()]

        field_names = [name for name in Product._meta.get_all_field_names() if name not in related_field_names]
        # field_names.append(['parameter','value'])
        writer.writerow(["Before getting params names", time.time() - start]) # profiling
        params_names = []
        for product in Product.objects.all():
            for parameter in product.get_parameter_values():
                if parameter.parameter.name not in params_names:
                    params_names.append(parameter.parameter.name)
        writer.writerow(["Get params names", time.time() - start])
        writer.writerow([i for i in field_names] + [i for i in params_names])
        writer.writerow(["Write column names", time.time() - start]) # profiling

        for product in Product.objects.all():
            #for parameter in product.get_parameter_values():
            writer.writerow([getattr(product, field, '') for field in field_names] + [parameter.value.value for parameter in product.get_parameter_values()])
        writer.writerow(["Write all data", time.time() - start]) # profiling
    else:
        pass

    # for a in field_names:
    #     writer.writerow([a])

    # strange_item = Product.objects.get(code='1235167')
    # for i in range(5000):
    #     strange_item.pk = None
    #     strange_item.code = int(strange_item.code) + 1
    #     strange_item.save()

    # writer.writerow(['Second row', 'A', 'B', 'C', '"Testing"', "Here's a quote"])

    return response
