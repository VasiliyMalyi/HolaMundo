from django.db import models
from django.utils.translation import pgettext_lazy, ugettext_lazy as _
from django.core.urlresolvers import reverse


class DataImport(models.Model):
    name = models.CharField(_('Import name'), max_length=256, default='new_import')
    creation_date = models.DateField(_('Created date'), auto_now_add=True, blank=True, null=True)
    last_edit_date = models.DateField(_('Updated date'), auto_now=True, blank=True, null=True)
    weight = models.PositiveIntegerField(_('Weight of import'), default=0)
    upload = models.FileField(_('Import file'), upload_to='import/')

    def __str__(self):
        return self.name

    # def get_absolute_url(self):
    #     if self.name == 'new_import':
    #         return reverse('dashboard:transfer-import-data', kwargs={"pk": self.id})
    #     else:
    #         return reverse('dashboard:transfer-import-data-all', kwargs={"pk": self.id})

    class Meta:
        verbose_name = _('Data Import')
        verbose_name_plural = _('Data Imports')


class ProductPricesTransfer(models.Model):
    name = models.CharField(_('Product name'), max_length=256)
    code = models.CharField(_('Code'), max_length=256, unique=True, blank=True, null=True)
    product_price = models.DecimalField(_("Import Price"), decimal_places=2, max_digits=12, blank=True, null=True)
    date_on_add = models.DateField(_('Created date'), auto_now_add=True, blank=True, null=True)

    def __str__(self):
        return self.name

    def get_columns(self):
        return [self.name, self.code, self.product_price]

    # @classmethod
    # def create(cls, code, price):
    #     new_obj = cls(code=code, product_price=price)
    #     # do something with the book
    #     return book

    class Meta:
        verbose_name = _('Product Price Transfer')
        verbose_name_plural = _('Product Price Transfers')
