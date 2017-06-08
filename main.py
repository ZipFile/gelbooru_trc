#!/usr/bin/env python3

import os
import re

from xml.sax.saxutils import escape

import cherrypy
import requests
import cachetools


re_space = re.compile(r'\s')
re_count = re.compile(r'count="(\d*?)"')


class InvalidTagName(Exception):
    pass


class InvalidApiResponse(Exception):
    pass


class NetError(Exception):
    pass


class SuspiciousResult(Exception):
    pass


class TooManyRequests(Exception):
    pass


tag_cache = cachetools.TTLCache(5000, 86400)
ip_cache = cachetools.TTLCache(1000, 10)


def get_count(tag, validate_tag=True):
    if validate_tag:
        if len(tag) > 60 or re_space.search(tag):
            raise InvalidTagName(tag)

    try:
        return tag_cache[tag]
    except KeyError:
        pass

    try:
        r = requests.get(
            'https://gelbooru.com/index.php',
            params={
                'page': 'dapi',
                's': 'post',
                'q': 'index',
                'limit': 0,
                'tags': tag,
            },
        )
    except requests.RequestException:
        raise NetError

    text = r.text

    if not text.startswith('<?xml'):
        raise InvalidApiResponse

    m = re_count.search(text)

    if not m:
        raise InvalidApiResponse

    try:
        count = int(m.group(1))
    except (ValueError, TypeError):
        count = 0

    tag_cache[tag] = count

    return count


class Gelbooru2TagsRatio:
    @cherrypy.expose
    def default(self, *args, **kwargs):
        result = ''
        debug = ''
        ip = cherrypy.request.remote.ip
        path = cherrypy.request.path_info.strip('/')
        tags = list(map(str.strip, path.split('+')))

        if len(tags) == 2:
            tag_a, tag_b = tags

            if ip in ip_cache:
                cherrypy.response.status =  429
                return "429 Too Many Requests"
            else:
                ip_cache[ip] = 1

            try:
                a_count = get_count(tag_a)

                if a_count <= 1000:
                    debug = '%s = %d' % (tag_a, a_count)
                    raise SuspiciousResult(tag_a)

                b_count = get_count(tag_b)

                if b_count <= 1000:
                    debug = '%s = %d; %s = %d' % (tag_a, a_count, tag_b, b_count)
                    raise SuspiciousResult(tag_b)

                ab_count = get_count(tag_a + ' ' + tag_b, False)
                total_count = ((a_count - ab_count) + (b_count - ab_count)) + ab_count

                debug = '%(a)s = %(na)d; %(b)s = %(nb)d, %(a)s & %(b)s = %(nab)d, %(a)s | %(b)s = %(nob)d' % {
                    'a': tag_a,
                    'b': tag_b,
                    'na': a_count,
                    'nb': b_count,
                    'nab': ab_count,
                    'nob': total_count,
                }

                if ab_count == 0:
                    result = '<span style="color: green">Ratio: 0. Congratulations, you won.</span>'
                elif total_count > 0:
                    ratio = ab_count / total_count

                    if ratio < 0.0001:
                        result = '<span>Ratio -> 0</span><br /><span>Not bad.</span>'
                    else:
                        result = '<span>Ratio: %.4f</span>' % ratio
                else:
                    result = '<span>Ratio: NaN</span><br /><span>Ooops, divided by zero!</span>'
            except InvalidTagName as e:
                result = '<span style="color: darkred">Invalid tag name <strong>%s</strong></span>' % escape(str(e))
            except NetError:
                result = '<span style="color: darkred">Failed to communicate with server</span>'
            except InvalidApiResponse:
                result = '<span style="color: darkred">Got invalid api response from gelbooru</span>'
            except SuspiciousResult as e:
                result = '<span style="color: darkorange">Tag <strong>%s</strong> looks suspicious, try more popular tag</span>' % escape(str(e))

        return '\n'.join([
            '<!doctype html>',
            '<div style="font-size: larger">%s</div>' % ' + '.join(map(escape, tags)),
            '<hr>',
            '<div>%s</div>' % result,
            '<div><code style="color: gray">%s</code></div>' % escape(debug),
        ])


if __name__ == '__main__':
    cherrypy.quickstart(Gelbooru2TagsRatio(), config={
        'global': {
            'server.socket_host': '0.0.0.0',
            'server.socket_port': int(os.environ.get('PORT', 8080)),
        },
    })
