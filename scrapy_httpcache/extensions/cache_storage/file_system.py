import gzip
import logging
import os
import pickle
from time import time
from typing import Dict, Optional, Union

from scrapy.http.headers import Headers
from scrapy.responsetypes import responsetypes
from scrapy.settings import Settings
from scrapy.utils.project import data_path
from scrapy.utils.python import to_bytes
from w3lib.http import headers_dict_to_raw, headers_raw_to_dict

from scrapy_httpcache import TRequest, TResponse, TSpider
from scrapy_httpcache.extensions.cache_storage import CacheStorage

logger = logging.getLogger(__name__)


class FilesystemCacheStorage(CacheStorage):
    def __init__(self, settings: Settings):
        super(FilesystemCacheStorage, self).__init__(settings)
        self.cachedir = data_path(settings["HTTPCACHE_DIR"])
        self.use_gzip = settings.getbool("HTTPCACHE_GZIP")
        self._open = gzip.open if self.use_gzip else open

    def open_spider(self, spider: TSpider) -> None:
        logger.debug(
            "Using filesystem cache storage in %(cachedir)s"
            % {"cachedir": self.cachedir},
            extra={"spider": spider},
        )

    def close_spider(self, spider: TSpider) -> None:
        pass

    def retrieve_response(
        self, spider: TSpider, request: TRequest
    ) -> Optional[TResponse]:
        """Return response if present in cache, or None otherwise."""
        metadata = self._read_meta(spider, request)
        if metadata is None:
            return  # not cached
        rpath = self._get_request_path(spider, request)
        with self._open(os.path.join(rpath, "response_body"), "rb") as f:
            body = f.read()
        with self._open(os.path.join(rpath, "response_headers"), "rb") as f:
            rawheaders = f.read()
        url = metadata.get("response_url")
        status = metadata["status"]
        headers = Headers(headers_raw_to_dict(rawheaders))
        respcls = responsetypes.from_args(headers=headers, url=url)
        response = respcls(url=url, headers=headers, status=status, body=body)
        return response

    def store_response(
        self, spider: TSpider, request: TRequest, response: TResponse
    ) -> None:
        """Store the given response in the cache."""
        rpath = self._get_request_path(spider, request)
        if not os.path.exists(rpath):
            os.makedirs(rpath)
        metadata = {
            "url": request.url,
            "method": request.method,
            "status": response.status,
            "response_url": response.url,
            "timestamp": time(),
        }
        with self._open(os.path.join(rpath, "meta"), "wb") as f:
            f.write(to_bytes(repr(metadata)))
        with self._open(os.path.join(rpath, "pickled_meta"), "wb") as f:
            pickle.dump(metadata, f, protocol=2)
        with self._open(os.path.join(rpath, "response_headers"), "wb") as f:
            f.write(headers_dict_to_raw(response.headers))
        with self._open(os.path.join(rpath, "response_body"), "wb") as f:
            f.write(response.body)
        with self._open(os.path.join(rpath, "request_headers"), "wb") as f:
            f.write(headers_dict_to_raw(request.headers))
        with self._open(os.path.join(rpath, "request_body"), "wb") as f:
            f.write(request.body)

    def _get_request_path(self, spider: TSpider, request: TRequest) -> str:
        key = self._request_key(request)
        return os.path.join(self.cachedir, spider.name, key[0:2], key)

    def _read_meta(
        self, spider: TSpider, request: TRequest
    ) -> Optional[Dict[str, Union[str, int, float]]]:
        rpath = self._get_request_path(spider, request)
        metapath = os.path.join(rpath, "pickled_meta")
        if not os.path.exists(metapath):
            return  # not found
        mtime = os.stat(metapath).st_mtime
        if 0 < self.expiration_secs < time() - mtime:
            return  # expired
        with self._open(metapath, "rb") as f:
            return pickle.load(f)
