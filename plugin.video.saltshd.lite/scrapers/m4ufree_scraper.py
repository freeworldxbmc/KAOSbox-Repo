"""
    SALTS XBMC Addon
    Copyright (C) 2014 tknorris

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import re
import urlparse
from salts_lib import dom_parser
from salts_lib import kodi
from salts_lib import log_utils
from salts_lib import scraper_utils
from salts_lib.constants import FORCE_NO_MATCH
from salts_lib.constants import QUALITIES
from salts_lib.constants import VIDEO_TYPES
import scraper


BASE_URL = 'http://m4ufree.info/'
AJAX_URL = '/demo.php?v=%s'
XHR = {'X-Requested-With': 'XMLHttpRequest'}

class M4UFree_Scraper(scraper.Scraper):
    base_url = BASE_URL

    def __init__(self, timeout=scraper.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.base_url = kodi.get_setting('%s-base_url' % (self.get_name()))

    @classmethod
    def provides(cls):
        return frozenset([VIDEO_TYPES.MOVIE])

    @classmethod
    def get_name(cls):
        return 'm4ufree'

    def resolve_link(self, link):
        return link

    def format_source_label(self, item):
        label = '[%s] %s' % (item['quality'], item['host'])
        if item['views'] is not None: label += ' (%s Views)' % (item['views'])
        return label

    def get_sources(self, video):
        source_url = self.get_url(video)
        hosters = []
        sources = []
        if source_url and source_url != FORCE_NO_MATCH:
            url = urlparse.urljoin(self.base_url, source_url)
            html = self._http_get(url, cache_limit=.5)
            
            views = None
            fragment = dom_parser.parse_dom(html, 'img', {'src': '[^"]*view_icon.png'})
            if fragment:
                match = re.search('(\d+)', fragment[0])
                if match:
                    views = match.group(1)
                
            match = re.search('href="([^"]+-full-movie-[^"]+)', html)
            if match:
                url = match.group(1)
                html = self._http_get(url, cache_limit=.5)
            
            sources = self.__get_sources(html)
            for link in dom_parser.parse_dom(html, 'span', {'class': '[^"]*btn-eps[^"]*'}, ret='link'):
                ajax_url = AJAX_URL % (link)
                ajax_url = urlparse.urljoin(self.base_url, ajax_url)
                headers = XHR
                headers['Referer'] = url
                html = self._http_get(ajax_url, headers=headers, cache_limit=.5)
                sources.update(self.__get_sources(html))
            
            for source in sources:
                if sources[source]['direct']:
                    host = self._get_direct_hostname(source)
                else:
                    host = urlparse.urlparse(source).hostname
                stream_url = source + '|User-Agent=%s' % (scraper_utils.get_ua())
                direct = sources[source]['direct']
                quality = sources[source]['quality']
                hoster = {'multi-part': False, 'host': host, 'class': self, 'quality': quality, 'views': views, 'rating': None, 'url': stream_url, 'direct': direct}
                hosters.append(hoster)

        return hosters
    
    def __get_sources(self, html):
        sources = {}
        for source in dom_parser.parse_dom(html, 'source', {'type': 'video/mp4'}, ret='src') + dom_parser.parse_dom(html, 'iframe', ret='src'):
            if self.base_url in source:
                redir_url = self._http_get(source, allow_redirect=False, method='HEAD', cache_limit=0)
                if redir_url.startswith('http'):
                    source = redir_url
            
            if self._get_direct_hostname(source) == 'gvideo':
                quality = scraper_utils.gv_get_quality(source)
                direct = True
            else:
                quality = QUALITIES.HD720
                direct = False
            
            sources[source] = {'quality': quality, 'direct': direct}
        
        return sources
    
    def search(self, video_type, title, year, season=''):
        results = []
        title = re.sub('[^A-Za-z0-9 ]', '', title)
        title = re.sub('\s+', '-', title)
        search_url = urlparse.urljoin(self.base_url, '/tag/%s' % (title))
        html = self._http_get(search_url, cache_limit=1)
        links = dom_parser.parse_dom(html, 'a', {'class': 'top-item'}, ret='href')
        titles = dom_parser.parse_dom(html, 'a', {'class': 'top-item'})
        for match_url, match_title_year in zip(links, titles):
            match_title_year = re.sub('</?cite>', '', match_title_year)
            match_title_year = re.sub('^Watch\s*', '', match_title_year)
            match = re.search('(.*?)\s+\(?(\d{4})\)?', match_title_year)
            if match:
                match_title, match_year = match.groups()
            else:
                match_title = match_title_year
                match_year = ''
            
            if not year or not match_year or year == match_year:
                result = {'title': scraper_utils.cleanse_title(match_title), 'year': match_year, 'url': scraper_utils.pathify_url(match_url)}
                results.append(result)

        return results
