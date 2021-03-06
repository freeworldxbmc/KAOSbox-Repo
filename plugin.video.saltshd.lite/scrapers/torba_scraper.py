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
import os
import re
import urllib
import urlparse
import xbmcvfs
from salts_lib import dom_parser
from salts_lib import kodi
from salts_lib import log_utils
from salts_lib import scraper_utils
from salts_lib.constants import FORCE_NO_MATCH
from salts_lib.constants import QUALITIES
from salts_lib.constants import VIDEO_TYPES
from salts_lib import gui_utils
from salts_lib import utils2
import scraper


XHR = {'X-Requested-With': 'XMLHttpRequest'}
BASE_URL = 'http://torba.se'
BASE_URL2 = 'http://streamtorrent.tv'
SEARCH_URL = '/%s/autocomplete?order=relevance&title=%s'
SEARCH_TYPES = {VIDEO_TYPES.MOVIE: 'movies', VIDEO_TYPES.TVSHOW: 'series'}
TOR_URL = BASE_URL2 + '/api/torrent/%s.json'
PL_URL = BASE_URL2 + '/api/torrent/%s/%s.m3u8'
INTERVALS = 5
EXPIRE_DURATION = 5 * 60
KODI_UA = 'Lavf/56.40.101'
M3U8_PATH = os.path.join(kodi.translate_path(kodi.get_profile()), 'torbase.m3u8')
M3U8_TEMPLATES = [[
    '#EXTM3U',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="{audio_group}",DEFAULT=YES,AUTOSELECT=YES,NAME="Stream 1",URI="{audio_stream}"',
    '',
    '#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH={bandwidth},NAME="{stream_name}",AUDIO="{audio_group}"',
    '{video_stream}'], [
    '#EXTM3U',
    '',
    '#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH={bandwidth},NAME="{stream_name}"',
    '{video_stream}']]
                  

class TorbaSe_Scraper(scraper.Scraper):
    base_url = BASE_URL

    def __init__(self, timeout=scraper.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.base_url = kodi.get_setting('%s-base_url' % (self.get_name()))
        self.auth_url = False

    @classmethod
    def provides(cls):
        return frozenset([VIDEO_TYPES.MOVIE, VIDEO_TYPES.TVSHOW, VIDEO_TYPES.EPISODE])

    @classmethod
    def get_name(cls):
        return 'torba.se'

    def resolve_link(self, link):
        try:
            xbmcvfs.delete(M3U8_PATH)
            query = urlparse.parse_qs(link)
            query = dict([(key, query[key][0]) if query[key] else (key, '') for key in query])
            if 'video_stream' in query:
                if self.__authorize_ip(query['video_stream']):
                    for template in M3U8_TEMPLATES:
                        f = xbmcvfs.File(M3U8_PATH, 'w')
                        try:
                            for line in template:
                                    line = line.format(**query)
                                    f.write(line + '\n')
                            else:
                                break
                        except:
                            log_utils.log('Unusable line in Torba M3U8: |%s|%s|' % (line, query), log_utils.LOGWARNING)
                    else:
                        log_utils.log('No usable M3U8 Template Found for link: %s' % (link), log_utils.LOGWARNING)
                        return
                        
                    f.close()
                    return M3U8_PATH
        except Exception as e:
            log_utils.log('Failure during torba resolver: %s' % (e), log_utils.LOGWARNING)

    def __authorize_ip(self, auth_url):
        self.auth_url = auth_url
        authorized, response = self.check_auth()
        if authorized:
            return response
        else:
            if 'url' in response:
                return gui_utils.do_ip_auth(self, response['url'], response.get('qrcode'))
            else:
                log_utils.log('Unusable JSON from Torba: %s' % (response), log_utils.LOGWARNING)
                return False
    
    def check_auth(self):
        if not self.auth_url:
            return True, None
        
        headers = {'User-Agent': KODI_UA}
        html = self._http_get(self.auth_url, headers=headers, cache_limit=0)
        try:
            js_data = utils2.json_loads_as_str(html)
            return False, js_data
        except:
            return True, html
    
    def format_source_label(self, item):
        label = '[%s] %s' % (item['quality'], item['host'])
        return label

    def get_sources(self, video):
        source_url = self.get_url(video)
        hosters = []
        if source_url and source_url != FORCE_NO_MATCH:
            url = urlparse.urljoin(self.base_url, source_url)
            html = self._http_get(url, cache_limit=.5)
            vid_link = dom_parser.parse_dom(html, 'a', {'class': '[^"]*video-play[^"]*'}, 'href')
            if vid_link:
                i = vid_link[0].rfind('/')
                if i > -1:
                    vid_id = vid_link[0][i + 1:]
                    stream_id = self.__get_stream_id(vid_id)
                    if stream_id:
                        pl_url = PL_URL % (vid_id, stream_id)
                        playlist = self._http_get(pl_url, cache_limit=.25)
                        sources = self.__get_streams_from_m3u8(playlist.split('\n'), BASE_URL2, vid_id, stream_id)
                        for source in sources:
                            hoster = {'multi-part': False, 'host': self._get_direct_hostname(source), 'class': self, 'quality': sources[source], 'views': None, 'rating': None, 'url': source, 'direct': True}
                            hosters.append(hoster)
                
        return hosters

    def __get_stream_id(self, vid_id):
        tor_url = TOR_URL % (vid_id)
        html = self._http_get(tor_url, cache_limit=.5)
        js_data = scraper_utils.parse_json(html, tor_url)
        if 'files' in js_data:
            for file_info in js_data['files']:
                if 'streams' in file_info and file_info['streams']:
                    return file_info['_id']
    
    def __get_streams_from_m3u8(self, playlist, st_url, vid_id, stream_id):
        sources = {}
        quality = QUALITIES.HIGH
        audio_group = ''
        audio_stream = ''
        stream_name = 'Unknown'
        bandwidth = 0
        for line in playlist:
            if line.startswith('#EXT-X-MEDIA'):
                match = re.search('GROUP-ID="([^"]+).*?URI="([^"]+)', line)
                if match:
                    audio_group, audio_stream = match.groups()
            if line.startswith('#EXT-X-STREAM-INF'):
                match = re.search('BANDWIDTH=(\d+).*?NAME="(\d+p)', line)
                if match:
                    bandwidth, stream_name = match.groups()
                    quality = scraper_utils.height_get_quality(stream_name)
            elif line.endswith('m3u8'):
                stream_url = urlparse.urljoin(st_url, line)
                query = {'audio_group': audio_group, 'audio_stream': audio_stream, 'stream_name': stream_name, 'bandwidth': bandwidth, 'video_stream': stream_url,
                         'vid_id': vid_id, 'stream_id': stream_id}
                stream_url = urllib.urlencode(query)
                sources[stream_url] = quality
                
        return sources
        
    def _get_episode_url(self, show_url, video):
        url = urlparse.urljoin(self.base_url, show_url)
        html = self._http_get(url, cache_limit=24)
        fragment = dom_parser.parse_dom(html, 'ul', {'class': 'season-list'})
        if fragment:
            match = re.search('href="([^"]+)[^>]+>\s*season\s+%s\s*<' % (video.season), fragment[0], re.I)
            if match:
                season_url = match.group(1)
                episode_pattern = 'href="([^"]*%s/%s/%s)"' % (show_url, video.season, video.episode)
                title_pattern = 'href="(?P<url>[^"]+)"[^>]*>\s*<div class="series-item-title">(?P<title>[^<]+)'
                return self._default_get_episode_url(season_url, video, episode_pattern, title_pattern)
    
    def search(self, video_type, title, year, season=''):
        results = []
        search_url = urlparse.urljoin(self.base_url, SEARCH_URL)
        search_url = search_url % (SEARCH_TYPES[video_type], urllib.quote_plus(title))
        html = self._http_get(search_url, headers=XHR, cache_limit=1)
        js_data = scraper_utils.parse_json(html, search_url)
        for item in js_data:
            if 'title' in item and 'link' in item:
                match_title = item['title']
                match_url = item['link']
                match_year = str(item.get('year', ''))
                if not year or not match_year or year == match_year:
                    result = {'title': scraper_utils.cleanse_title(match_title), 'year': match_year, 'url': scraper_utils.pathify_url(match_url)}
                    results.append(result)

        return results
                                         
                                         