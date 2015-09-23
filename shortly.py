# -*- coding: utf-8 -*-
import os
import redis
import urlparse
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.wsgi import SharedDataMiddleware
from werkzeug.utils import redirect
from jinja2 import Environment, FileSystemLoader


class shortly(object):
    def __init__(self, config):
        self.redis = redis.Redis(config['redis_host'], config['redis_port'])

        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(loader=FileSystemLoader(template_path), autoescape=True)

        self.url_map = Map([
            Rule('/', endpoint='new_url'),
            Rule('/<short_id>', endpoint='follow_short_link'),
            Rule('/<short_id>+', endpoint='short_link_details')
        ])

        # import pdb
        # pdb.set_trace()

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype='text/html')

    def on_new_url(self, request):
        error = None
        url = ''
        # import pdb
        # pdb.set_trace()
        if request.method == 'POST':
            url = request.form['url']
            if not is_valid_url(url):
                error = 'Please enter a valid URL'
            else:
                short_id = self.insert_url(url)
                return redirect('/%s+' % short_id)

        # тут соберем в список словарей все уже сохраненные короткие ссылки
        all_shortlies = self.get_all_shortlies()

        return self.render_template('new_url.html', error=error, url=url, list_shortlies=all_shortlies)

    def get_all_shortlies(self):
        """
        Метод для получения всех сохраненных ссылок. Возвращает список словарей каждой ссылки
        """
        links_list = []
        num_saved_links = int(self.redis.get('last_url_id') or 0) + 1
        for link in range(1, num_saved_links):
            short_id = base36_encode(link)
            link_target = self.redis.get('url_target:' + short_id)
            click_count = int(self.redis.get('click-count:' + short_id) or 0)
            links_list.append(dict(short_id = short_id, url_target = link_target, click_count = click_count))

        # import pdb
        # pdb.set_trace()
        return links_list

    def on_follow_short_link(self, request, short_id):
        """
        Вызывается при переходе на shortly-ссылку - переходим на полную ссылку
        """
        link_target = self.redis.get('url_target:' + short_id)
        if link_target is None:
            raise NotFound()
        self.redis.incr('click-count:' + short_id)
        return redirect(link_target)

    def on_short_link_details(self, request, short_id):
        link_target = self.redis.get('url_target:' + short_id)
        if link_target is None:
            raise NotFound()
        click_count = int(self.redis.get('click-count:' + short_id) or 0)
        return self.render_template('short_link_details.html', link_target=link_target,
                                    short_id=short_id, click_count=click_count)

    def dispatch_request(self, request):
        """
        Метод Диспетчер
        """
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            # import pdb
            # pdb.set_trace()
            return getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException, e:
            return e

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def insert_url(self, url):
        short_id = self.redis.get('reverse-url:' + url)
        if short_id is not None:
            return short_id
        url_num = self.redis.incr('last_url_id')
        short_id = base36_encode(url_num)
        self.redis.set('url_target:' + short_id, url)
        self.redis.set('reverse-url:' + url, short_id)
        return short_id

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


def is_valid_url(url):
    """
    Валидация по схеме в URL
    """
    parts = urlparse.urlparse(url)
    return parts.scheme in ('http', 'https')


def base36_encode(number):
    assert number >= 0, 'positive integer required'
    if number == 0:
        return 0
    base36 = []
    while number != 0:
        number, i = divmod(number, 36)
        base36.append('0123456789abcdefghijklmnopqrstuvwxyz'[i])
    return ''.join(reversed(base36))


def create_app(redis_host='localhost', redis_port=6379, with_static=True):
    app = shortly({
        'redis_host': redis_host,
        'redis_port': redis_port
    })
    if with_static:
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app,
                {'/static': os.path.join(os.path.dirname(__file__), 'static')})
    return app


if __name__ == '__main__':
    from werkzeug.serving import run_simple

    app = create_app()
    run_simple('127.0.0.1', 5001, app, use_debugger=True, use_reloader=True)
