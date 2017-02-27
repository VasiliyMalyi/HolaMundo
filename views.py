import csv
import time
import datetime
import pyexcel
import django_excel as excel
from decimal import Decimal
from collections import OrderedDict

from django.core.urlresolvers import reverse
from django.views.generic import UpdateView, ListView, CreateView, DetailView
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.conf import settings
from django.db.models import Q, QuerySet
from django.contrib import messages


from mediaset.shop.catalogue.models import (
    Product, ProductImage, Category, ProductImage, NewProductParameterValue, NewParameter,
    NewCategoryParameter, NewParameterValue, CarBrandModel)
from mediaset.dashboard.catalogue.forms import ProductListImageFormSet, ProductFilter
from mediaset.shop.stock.models import StockRecord, Provider
from mediaset.dashboard.transfer.forms import DataImportForm, DataImportAllForm
from mediaset.dashboard.transfer.models import DataImport, ProductPricesTransfer
from mediaset.dashboard.transfer.forms import ProductFormSet


class UploadImagesView(ListView):
    model = Product
    template_name = 'dashboard/transfer/images.html'
    image_formset = ProductListImageFormSet
    context_object_name = 'products'
    paginate_by = 20

    search_form_class = ProductFilter

    def get_products(self, ctx):
        products = ctx.get('object_list') or self.model.objects.all()
        if not isinstance(products, QuerySet):
            ids = [product.id for product in products]
            products = self.model.objects.filter(id__in=ids)
        return products

    def get_queryset(self):
        queryset = super().get_queryset().order_by('code')
        queryset = self.apply_search(queryset)
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['search_form'] = self.search_form_class(self.request.GET)

        products = self.get_queryset()

        for product in products:
            if '{}_image_formset'.format(product.code) not in ctx:
                ctx['{}_image_formset'.format(product.code)] = self.image_formset(
                    product, instance=product, prefix=product.code)

        return ctx

    def apply_search(self, queryset):
        self.form = self.search_form_class(self.request.GET)

        if not self.form.is_valid():
            return queryset

        data = self.form.cleaned_data

        if data.get('code'):
            matches_upc = Product.objects.filter(code=data['code'])
            qs_match = queryset.filter(
                Q(id__in=matches_upc.values('id')) | Q(id__in=matches_upc.values('parent_id')))

            if qs_match.exists():
                queryset = qs_match
            else:
                matches_upc = Product.objects.filter(code__icontains=data['code'])
                queryset = queryset.filter(
                    Q(id__in=matches_upc.values('id')) | Q(id__in=matches_upc.values('parent_id')))

        if data.get('name'):
            queryset = queryset.filter(name__icontains=data['name'])

        if data.get('category'):
            matches_upc = Product.objects.filter(category=data['category'])
            queryset = queryset.filter(
                Q(id__in=matches_upc.values('id')) |
                Q(parent_id__in=matches_upc.values('id')))

        return queryset

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') is not None:
            return super().post(request, *args, **kwargs)

        self.object_list = self.get_queryset()

        ctx = self.get_context_data()

        products = self.get_products(ctx)
        image_formsets = dict()
        for product in products:
            image_formsets[product.code] = self.image_formset(
                product, data=self.request.POST, files=self.request.FILES, instance=product, prefix=product.code)

        is_valid = all([formset.is_valid() for formset in image_formsets.values()])

        if is_valid:
            return self.all_formset_valid(image_formsets)
        else:
            return self.all_formset_invalid(image_formsets)

    def all_formset_valid(self, image_formsets):
        for f in image_formsets.values():
            f.save()
        return HttpResponseRedirect(self.get_success_url())

    def all_formset_invalid(self, image_formsets):
        ctx = dict()
        for product_code in stock_formsets.keys():
            ctx['{}_image_formset'.format(product_code)] = image_formsets[product_code]

        return self.render_to_response(self.get_context_data(**ctx))

    def get_success_url(self):
        messages.success(self.request, "Готово")

        # action = self.request.POST.get('action')
        url = reverse('dashboard:product-list')
        return url


class UploadView(CreateView):
    model = DataImport
    template_name = 'dashboard/transfer/upload.html'
    form_class = DataImportForm
    context_object_name = 'data_import'
    url = 'dashboard:transfer-import-data'

    def get_success_url(self):
        return reverse(self.url, kwargs={"pk": self.object.id})


class UploadAllView(UploadView):
    template_name = 'dashboard/transfer/upload_all.html'
    form_class = DataImportAllForm
    url = 'dashboard:transfer-import-data-all'


class ImportDataView(DetailView):
    model = DataImport
    context_object_name = 'data_import'
    template_name = 'dashboard/transfer/data.html'

    def dispatch(self, request, *args, **kwargs):
        ProductPricesTransfer.objects.all().delete()
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        obj = super().get_object()
        obj = obj.upload
        try:
            obj = pyexcel.get_book_dict(file_type='xlsx', file_content=obj.read())
        except Exception:
            raise Http404('Некорректный загружаемый файл')
        obj = self.get_validation(obj)
        return obj

    def post(self, request, *args, **kwargs):
        data = dict(request.POST)
        if not data:
            raise ValueError('No POST data')

        d = dict(zip(data['pi'], data['pp']))
        for code, price in d.items():
            try:
                ProductPricesTransfer.objects.create(name='item', code=code,
                                                     product_price=Decimal(str(price).replace(',', '.')))
            except Exception:
                raise Http404('Товар с кодом {} содержит некорректные данные. '
                              'Убедитесь в том, что в поле цена указано корректное число'.format(code))

        return HttpResponseRedirect(reverse("dashboard:transfer-import-prices"))

    def get_validation(self, data):
        for k, v in data.items():
            # try:
            #     category = Category.objects.get(name=k)
            # except Exception:
            #     raise Http404('Категории {} не существует'.format(k))
            if v[0] != ['name', 'code', 'price']:
                raise Http404('Некорректные названия колонок.'
                              'Убедитесь, что всего 3 колонки и их названия: name, code, price')
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


class ImportDataAllView(DetailView):
    model = DataImport
    context_object_name = 'data_import'
    template_name = 'dashboard/transfer/all_data.html'
    new_objects = {}
    message = ''
    default_provider = settings.COMPANY

    def get(self, request, *args, **kwargs):
        # self.new_objects = {}
        if request.GET.get('submit') == 'Проверить':
            new_objects_list = {}
            data = self.get_object()
            for k, v in data.items():
                if not Category.objects.filter(name=k).exists():
                    raise Http404('Категории {} не существует'.format(k))
                new_obj_list = []
                for index, item in enumerate(v):
                    if index == 0:
                        if item[0] != 'name' or item[1] != 'code' or item[2] != 'first_text' or item[3] != 'price' \
                                or item[4] != 'provider' or item[5] != 'num_in_stock' or item[6] != 'destination':
                            raise Http404('Некорректные названия колонок. '
                                          'Убедитесь, что первых 7 колонок имеют названия: '
                                          'name, code, first_text, price, provider, num_in_stock, destination')
                        param_names = item[7:]
                        if param_names:
                            for param in param_names:
                                if not NewParameter.objects.filter(name=param, category__name=k).exists():
                                    raise Http404('Не существует параметра {} в категории {}'.format(param, k))
                        new_obj_list = [['name', 'code', 'first_text', 'price', 'provider', 'num_in_stock', 'destination'] + param_names]
                    else:
                        if not Product.objects.filter(code=item[1]).exists():
                            new_obj_list.append(item)
                if len(new_obj_list) > 1:
                    new_objects_list.update({k: new_obj_list})
            if new_objects_list:
                self.new_objects = new_objects_list
            else:
                self.message = "Не обнаружено уникальных кодов. Все загружаемые товары уже есть на сайте"

        return super().get(request, *args, **kwargs)

    def get_object(self, queryset=None):
        obj = super().get_object()
        obj = obj.upload
        try:
            obj = pyexcel.get_book_dict(file_type='xlsx', file_content=obj.read())
        except Exception:
            raise Http404('Некорректный загружаемый файл')
        return obj

    def post(self, request, *args, **kwargs):
        new_objects_list = {}
        data = self.get_object()
        for k, v in data.items():
            if not Category.objects.filter(name=k).exists():
                raise Htt404('Категории {} не существует'.format(k))
            new_obj_list = []
            for index, item in enumerate(v):
                if index == 0:
                    if item[0] != 'name' or item[1] != 'code' or item[2] != 'first_text' or item[3] != 'price' \
                            or item[4] != 'provider' or item[5] != 'num_in_stock' or item[6] != 'destination':
                        raise Http404('Некорректные названия колонок. '
                                      'Убедитесь, что первых 7 колонок имеют названия: '
                                      'name, code, first_text, price, provider, num_in_stock, destination')
                    param_names = item[7:]
                    if param_names:
                        for param in param_names:
                            if not NewParameter.objects.filter(name=param, category__name=k).exists():
                                raise Http404('Не существует параметра {} в категории {}'.format(param, k))
                    new_obj_list = [['name', 'code', 'first_text', 'price', 'provider', 'num_in_stock', 'destination'] + param_names]
                else:
                    if not Product.objects.filter(code=item[1]).exists():
                        new_obj_list.append(item)
            if len(new_obj_list) > 1:
                new_objects_list.update({k: new_obj_list})
        if new_objects_list:
            self.new_objects = new_objects_list
        if self.new_objects:
            for k, v in self.new_objects.items():
                param_names = []
                for index, item in enumerate(v):
                    if index == 0:
                        param_names = item[7:]
                    else:
                        if not Product.objects.filter(code=item[1]).exists():
                            Product.objects.create(name=item[0],
                                                   code=item[1],
                                                   category=Category.objects.get(name=k),
                                                   first_text=item[2]
                                                   )

                            new_obj = Product.objects.get(code=item[1])
                            import_price = item[3]
                            try:
                                item[5] = Decimal(item[5])
                            except Exception:
                                item[5] = 1
                            if Provider.objects.filter(name=item[4]).exists() and import_price:
                                StockRecord.objects.create(product=new_obj,
                                                           price=import_price,
                                                           provider=Provider.objects.get(name=item[4]),
                                                           num_in_stock=item[5])
                            elif not item[3] and Provider.objects.filter(name=item[4]).exists():
                                StockRecord.objects.create(product=new_obj,
                                                           price=0,
                                                           provider=Provider.objects.get(name=item[4]),
                                                           num_in_stock=item[5])
                            elif item[3] and not Provider.objects.filter(name=item[4]).exists():
                                StockRecord.objects.create(product=new_obj,
                                                           price=import_price,
                                                           provider=Provider.objects.get(name=str(self.default_provider)),
                                                           num_in_stock=item[5])
                            else:
                                StockRecord.objects.create(product=new_obj,
                                                           price=0,
                                                           provider=Provider.objects.get(name=str(self.default_provider)),
                                                           num_in_stock=item[5])  # edit name
                            if item[6]:
                                for destination in item[6].split(', '):
                                    if CarBrandModel.objects.filter(value=destination).exists():
                                        new_obj.destination.add(CarBrandModel.objects.get(value=destination))
                            if param_names:
                                for j in list(zip(param_names, item[7:])):
                                    if j[1] and NewParameterValue.objects.filter(value=j[1]).exists():
                                        NewProductParameterValue.objects.create(product=new_obj,
                                                                                parameter=NewParameter.objects.get(name=j[0]),
                                                                                value=NewParameterValue.objects.get(value=j[1],
                                                                                                                    parameter=NewParameter.objects.get(name=j[0])))
            self.new_objects = {}

            return HttpResponseRedirect(reverse("dashboard:product-list"))
        else:
            raise ValueError('No POST data')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx_update = {
            'new_objects': self.new_objects,
            'message': self.message
        }

        ctx.update(ctx_update)

        return ctx


class ImportProductPricesView(ListView):
    model = Product
    template_name = 'dashboard/transfer/data_prices.html'
    context_object_name = 'products'

    def post(self, request, *args, **kwargs):
        post_data = dict(request.POST)
        if not post_data:
            raise ValueError('No POST data')

        d = dict(zip(post_data['item'], post_data['new']))
        products_records = StockRecord.objects.filter(product__code__in=d.keys())
        for product_record in products_records:
            for k, v in d.items():
                if product_record.product.code == k:
                    product_record.price = Decimal(str(v).replace(',', '.'))
                    product_record.save()

        return HttpResponseRedirect(reverse("dashboard:product-list"))

    def get_queryset(self):
        products = super().get_queryset()
        filtered_list = []
        for product in products:
            inner_list = []
            if ProductPricesTransfer.objects.filter(code=product.code).exists():
                new_product_price = ProductPricesTransfer.objects.get(code=product.code).product_price
            else:
                continue
            if StockRecord.objects.filter(product=product).exists():
                stock_record_price = StockRecord.objects.get(product=product).price
                if stock_record_price != new_product_price:
                    inner_list.append(product.name)
                    inner_list.append(product.code)
                    inner_list.append(stock_record_price)
                    inner_list.append(new_product_price)
                    filtered_list.append(inner_list)

        return filtered_list

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx_update = {
            'test': self.get_queryset(),
        }

        ctx.update(ctx_update)

        return ctx


def export_prices_view(request):
    start = time.time()  # profiling
    sheets = {}
    category_list = [i for i in Category.objects.all() if Product.objects.filter(category__name=i.name).exists()]
    for category in category_list:
        field_names = ['name', 'code']

        arr_title = [[str(i) for i in field_names] + ['price']]
        cat_objects = Product.objects.filter(category__name=category.name).order_by('category', 'id')
        arr = []
        for i in cat_objects:
            arr_add = []
            for field in field_names:
                arr_add.append(str(getattr(i, field, '')))
            try:
                arr_add.append(str(StockRecord.objects.get(product=i.id).price))
            except Exception:
                arr_add.append('0')
            arr.append(arr_add)

        sheet = pyexcel.Sheet(arr_title + arr)
        if "/" not in category.name and cat_objects:
            sheets.update({str(category.name): sheet})  # {"Category":sheet1, "Product":sheet2}

    book = pyexcel.Book(sheets=sheets)
    file_name = "Prices_{}".format(str(datetime.date.today()))

    return excel.make_response(book, file_type='xlsx', file_name=file_name, status=200)


def export_products_view(request):
    start = time.time()  # profiling

    sheets = {}
    category_list = [i for i in Category.objects.all() if Product.objects.filter(category__name=i.name).exists()]
    for category in category_list:
        field_names = ['name', 'code', 'first_text']  # 'first_text'

        parameter_names = list(set([i.parameter.name for i in NewCategoryParameter.objects.all()
                                    if i.category.name == category.name]))
        arr_title = [[str(i) for i in field_names] + ['price'] + ['provider'] + ['num_in_stock'] + ['destination'] + parameter_names]

        cat_objects = Product.objects.filter(category__name=category.name).order_by('code')
        arr = []
        for i in cat_objects:
            arr_add = []
            for field in field_names:
                arr_add.append(str(getattr(i, field, '')))
            if StockRecord.objects.filter(product=i.id).exists():
                arr_add.append(str(StockRecord.objects.get(product=i.id).price))
                arr_add.append(str(StockRecord.objects.get(product=i.id).provider.name))
                arr_add.append(str(StockRecord.objects.get(product=i.id).num_in_stock))
            else:
                arr_add.append('0')
                arr_add.append('')
            # if ProductImage.objects.filter(product=i.id).exists():
            #     arr_add.append(str(ProductImage.objects.get(product=i.id).image_original))
            # else:
            #     arr_add.append('')
            dest_list = []
            for dest in i.destination.all():
                dest_list.append(str(dest.value))
            arr_add.append(str(', '.join(dest_list)))
            for param in parameter_names:
                if NewProductParameterValue.objects.filter(product=i.id, parameter__name=param).exists():
                    arr_add.append(
                        NewProductParameterValue.objects.get(product=i.id, parameter__name=param).value.value)
                else:
                    arr_add.append('')
            # ts = time.time() - start  # profiling
            # arr_add.append(ts)  # profiling
            arr.append(arr_add)

        time_stump = time.time() - start  # profiling

        sheet = pyexcel.Sheet(arr_title + arr)
        if "/" not in category.name and cat_objects:
            sheets.update({str(category.name): sheet})  # {"Category":sheet1, "Product":sheet2}

    book = pyexcel.Book(sheets=sheets)
    file_name = "All_{}".format(str(datetime.date.today()))

    return excel.make_response(book, file_type='xlsx', file_name=file_name, status=200)


def export_blank_view(request):
    sheets = {}
    category_list = [i for i in Category.objects.all()]
    for category in category_list:
        field_names = ['name', 'code', 'first_text']  # 'first_text'

        parameter_names = list(set([i.parameter.name for i in NewCategoryParameter.objects.all()
                                    if i.category.name == category.name]))
        arr_title = [[str(i) for i in field_names] + ['price'] + ['provider'] + ['num_in_stock'] + ['destination'] + parameter_names]

        sheet = pyexcel.Sheet(arr_title)
        if "/" not in category.name:
            sheets.update({str(category.name): sheet})

    book = pyexcel.Book(sheets=sheets)
    file_name = "Blank_{}".format(str(datetime.date.today()))

    return excel.make_response(book, file_type='xlsx', file_name=file_name, status=200)


