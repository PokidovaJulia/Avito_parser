import datetime
import urllib.parse
from logging import getLogger

import bs4
import requests
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from apars.models import Product
from apars.models import Task
from apars.constants import STATUS_NEW
from apars.constants import STATUS_READY

logger = getLogger(__name__)

class AvitoParser:
    PAGE_LIMIT = 10
    def __init__(self):
        self.session = requests.Session()
        self.session.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.2 Safari/605.1.15',
            'Accept-Language': 'ru',
        }
        self.task = None

    def find_task(self):
        obj = Task.objects.filter(status=STATUS_NEW).first()
        if not obj:
            raise CommandError('no tasks found')
        self.task = obj
        logger.info(f'Работа над заданием {self.task}')

    def finish_task(self):
        self.task.status = STATUS_READY
        self.task.save()
        logger.info(f'Завершение задания')

    def get_page(self, page: int = None):
        params = {
            'radius': 0,
            'user': 1,
        }
        if page and page > 1:
            params['p'] = page

        url = self.task.url
        r = self.session.get(url, params=params)
        r.raise_for_status()
        return r.text

    def parse_block(self, item):
        url_block = item.select_one('a.snippet-link')
        if not url_block:
            raise CommandError('bad "url_block" css')
        href = url_block.get('href')  # Через метод get передается атрибут href, когда получаем href и складывааем его с доменом то олучаем ссылку.
        if href:
            url = 'https://www.avito.ru' + href
        else:
            url = None

        # Выбор блока с названием.
        title_block = item.select_one('h3.snippet-title a')
        if not title_block:
            raise CommandError('bad "title_block" css')
        title = title_block.string.strip()  # Метод стрип удалит пробелы вначале и в конце строки.

        # Валюта и цена
        price_block = item.select_one('span.snippet-price')
        if not price_block:
            raise CommandError('bad "price_block" css')
        price_block = price_block.get_text('\n')
        price_block = price_block.replace(' ', '')
        currency = ''.join(s for s in price_block if not s.isdigit())
        price = ''.join(s for s in price_block if s.isdigit())

        try:
            p = Product.objects.get(url=url)
            p.task = self.task
            p.title = title
            p.price = price
            p.currency = currency
            p.save()
        except Product.DoesNotExist:
            p = Product(
                task=self.task,
                url=url,
                title=title,
                price=price,
                currency=currency,
            ).save()
        logger.debug(f'product {p}')


    def get_pagination_limit(self):
        text = self.get_page()
        soup = bs4.BeautifulSoup(text, 'lxml')

        container = soup.select('a.pagination-page')
        if not container:
            return  1
        last_button = container[-1]
        href = last_button.get('href')
        if not href:
            return 1

        r = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(r.query)
        return min(int(params['p'][0]), self.PAGE_LIMIT)

    def get_blocks(self, page: int = None):
        text = self.get_page(page=page)
        soup = bs4.BeautifulSoup(text, 'lxml')

        # Запрос css-селектора, состоящего из множества классов, производитс чкрез stltct.
        container = soup.select('div.snippet-horizontal.item.item_table.clearfix.js-catalog-item-enum.item-with-contact.js-item-extended')
        for item in container:
            self.parse_block(item=item)

    '''Данная функция узнает limit из функции get_pagination_limit'''

    def parse_all(self):
        # Поиск задания
        self.find_task()

        limit = self.get_pagination_limit()
        logger.info(f'Всего страниц: {limit}')
        for i in range(1, limit + 1):
            logger.info(f'Работа над страницей {i}')
            self.blocks = self.get_blocks(page=i)
            break

        # Завершение задания
        self.finish_task()

class Command(BaseCommand):
    help = 'Парсинг Авито'

    def handle(self, *args, **options):
        p = AvitoParser()
        p.parse_all()