import json
import random
from typing import List, Dict
from copy import deepcopy
from urllib.parse import urlparse

from instagrapi.utils import InstagramIdCodec
from instagrapi.exceptions import (
    ClientError,
    ClientNotFoundError,
    MediaNotFound,
    ClientLoginRequired
)
from instagrapi.extractors import (
    extract_media_v1, extract_media_gql,
    extract_media_oembed, extract_location
)
from instagrapi.types import (
    Usertag, Location, UserShort, Media
)


class MediaMixin:
    """
    Helpers for media
    """
    _medias_cache = {}  # pk -> object

    def media_id(self, media_pk: int) -> str:
        """
        Get full media id

        Parameters
        ----------
        media_pk: int
            Unique Media ID

        Returns
        -------
        str
            Full media id

        Example
        -------
        2277033926878261772 -> 2277033926878261772_1903424587
        """
        media_id = str(media_pk)
        if "_" not in media_id:
            assert media_id.isdigit(), (
                "media_id must been contain digits, now %s" % media_id
            )
            user = self.media_user(media_id)
            media_id = "%s_%s" % (media_id, user.pk)
        return media_id

    @staticmethod
    def media_pk(media_id: str) -> int:
        """
        Get short media id

        Parameters
        ----------
        media_id: str
            Unique Media ID

        Returns
        -------
        str
            media id
        """
        media_pk = str(media_id)
        if "_" in media_pk:
            media_pk, _ = media_id.split("_")
        return int(media_pk)

    @staticmethod
    def media_pk_from_code(code: str) -> int:
        """
        Get Media PK from Code

        Parameters
        ----------
        code: str
            Code

        Returns
        -------
        int
            Full media id

        Examples
        --------
        B1LbfVPlwIA -> 2110901750722920960
        B-fKL9qpeab -> 2278584739065882267
        CCQQsCXjOaBfS3I2PpqsNkxElV9DXj61vzo5xs0 -> 2346448800803776129
        """
        return InstagramIdCodec.decode(code[:11])

    def media_pk_from_url(self, url: str) -> int:
        """
        Get Media PK from URL

        Parameters
        ----------
        url: str
            URL of the media

        Returns
        -------
        int
            Media PK

        Examples
        --------
        https://instagram.com/p/B1LbfVPlwIA/ -> 2110901750722920960
        https://www.instagram.com/p/B-fKL9qpeab/?igshid=1xm76zkq7o1im -> 2278584739065882267
        """
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p]
        return self.media_pk_from_code(parts.pop())

    def media_info_a1(self, media_pk: int, max_id: str = None) -> Media:
        """
        Get Media from PK

        Parameters
        ----------
        media_pk: int
            Unique identifier of the media
        max_id: str, optional
            Max ID, default value is None

        Returns
        -------
        Media
            An object of Media type
        """
        media_pk = self.media_pk(media_pk)
        shortcode = InstagramIdCodec.encode(media_pk)
        """Use Client.media_info
        """
        params = {"max_id": max_id} if max_id else None
        data = self.public_a1_request(
            "/p/{shortcode!s}/".format(**{"shortcode": shortcode}), params=params
        )
        if not data.get("shortcode_media"):
            raise MediaNotFound(media_pk=media_pk, **data)
        return extract_media_gql(data["shortcode_media"])

    def media_info_gql(self, media_pk: int) -> Media:
        """
        Get Media from PK

        Parameters
        ----------
        media_pk: int
            Unique identifier of the media

        Returns
        -------
        Media
            An object of Media type
        """
        media_pk = self.media_pk(media_pk)
        shortcode = InstagramIdCodec.encode(media_pk)
        """Use Client.media_info
        """
        variables = {
            "shortcode": shortcode,
            "child_comment_count": 3,
            "fetch_comment_count": 40,
            "parent_comment_count": 24,
            "has_threaded_comments": False,
        }
        data = self.public_graphql_request(
            variables, query_hash="477b65a610463740ccdb83135b2014db"
        )
        if not data.get("shortcode_media"):
            raise MediaNotFound(media_pk=media_pk, **data)
        if data['shortcode_media']['location']:
            data['shortcode_media']['location'] = self.location_complete(
                extract_location(data['shortcode_media']['location'])
            ).dict()
        return extract_media_gql(data["shortcode_media"])

    def media_info_v1(self, media_pk: int) -> Media:
        """
        Get Media from PK

        Parameters
        ----------
        media_pk: int
            Unique identifier of the media

        Returns
        -------
        Media
            An object of Media type
        """
        try:
            result = self.private_request(f"media/{media_pk}/info/")
        except ClientNotFoundError as e:
            raise MediaNotFound(e, media_pk=media_pk, **self.last_json)
        except ClientError as e:
            if "Media not found" in str(e):
                raise MediaNotFound(e, media_pk=media_pk, **self.last_json)
            raise e
        return extract_media_v1(result["items"].pop())

    def media_info(self, media_pk: int, use_cache: bool = True) -> Media:
        """
        Get Media Information from PK

        Parameters
        ----------
        media_pk: int
            Unique identifier of the media
        use_cache: bool, optional
            Whether or not to use information from cache, default value is True

        Returns
        -------
        Media
            An object of Media type
        """
        media_pk = self.media_pk(media_pk)
        if not use_cache or media_pk not in self._medias_cache:
            try:
                try:
                    media = self.media_info_gql(media_pk)
                except ClientLoginRequired as e:
                    if not self.inject_sessionid_to_public():
                        raise e
                    media = self.media_info_gql(media_pk)  # retry
            except Exception as e:
                if not isinstance(e, ClientError):
                    self.logger.exception(e)  # Register unknown error
                # Restricted Video: This video is not available in your country.
                # Or private account
                media = self.media_info_v1(media_pk)
            self._medias_cache[media_pk] = media
        return deepcopy(self._medias_cache[media_pk])  # return copy of cache (dict changes protection)

    def media_delete(self, media_id: str) -> bool:
        """
        Delete media by Media ID

        Parameters
        ----------
        media_id: str
            Unique identifier of the media

        Returns
        -------
        bool
            A boolean value
        """
        assert self.user_id, "Login required"
        media_id = self.media_id(media_id)
        result = self.private_request(
            f"media/{media_id}/delete/", self.with_default_data(
                {"media_id": media_id}
            )
        )
        self._medias_cache.pop(self.media_pk(media_id), None)
        return result.get("did_delete")

    def media_edit(
        self,
        media_id: str,
        caption: str,
        title: str = "",
        usertags: List[Usertag] = [],
        location: Location = None
    ) -> Dict:
        """
        Edit caption for media

        Parameters
        ----------
        media_id: str
            Unique identifier of the media
        caption: str
            Media caption
        title : str
            Title of the media
        usertags: List[Usertag], optional
            List of users to be tagged on this upload, default is empty list.
        location: Location, optional
            Location tag for this upload, default is None

        Returns
        -------
        Dict
            A dictionary of response from the call
        """
        assert self.user_id, "Login required"
        media_id = self.media_id(media_id)
        media = self.media_info(media_id)  # from cache
        usertags = [
            {"user_id": tag.user.pk, "position": [tag.x, tag.y]}
            for tag in usertags
        ]
        data = {
            "caption_text": caption,
            "container_module": "edit_media_info",
            "feed_position": "0",
            "location": self.location_build(location),
            "usertags": json.dumps({"in": usertags}),
            "is_carousel_bumped_post": "false",
        }
        if media.product_type == "igtv":
            if not title:
                try:
                    title, caption = caption.split("\n", 1)
                except ValueError:
                    title = caption[:75]
            data = {
                "caption_text": caption,
                "title": title,
                "igtv_ads_toggled_on": "0",
            }
        self._medias_cache.pop(self.media_pk(media_id), None)  # clean cache
        result = self.private_request(
            f"media/{media_id}/edit_media/", self.with_default_data(data),
        )
        return result

    def media_user(self, media_pk: int) -> UserShort:
        """
        Get author of the media

        Parameters
        ----------
        media_pk: int
            Unique identifier of the media

        Returns
        -------
        UserShort
            An object of UserShort
        """
        return self.media_info(media_pk).user

    def media_oembed(self, url: str) -> Dict:
        """
        Return info about media and user from post URL

        Parameters
        ----------
        url: str
            URL for a media

        Returns
        -------
        Dict
            A dictionary of response from the call
        """
        return extract_media_oembed(
            self.private_request(f"oembed?url={url}")
        )

    def media_like(self, media_id: str, revert: bool = False) -> bool:
        """
        Like a media

        Parameters
        ----------
        media_id : str
            Unique identifier of a Media
        revert: bool, optional
            If liked, whether or not to unlike. Default is False

        Returns
        -------
        bool
            A boolean value
        """
        assert self.user_id, "Login required"
        media_id = self.media_id(media_id)
        data = {
            "inventory_source": "media_or_ad",
            "media_id": media_id,
            "radio_type": "wifi-none",
            "is_carousel_bumped_post": "false",
            "container_module": "feed_timeline",
            "feed_position": str(random.randint(0, 6))
        }
        name = 'unlike' if revert else 'like'
        result = self.private_request(
            f"media/{media_id}/{name}/",
            self.with_action_data(data)
        )
        return result['status'] == 'ok'

    def media_unlike(self, media_id: str) -> bool:
        """
        Unlike a media

        Parameters
        ----------
        media_id : str
            Unique identifier of a Media

        Returns
        -------
        bool
            A boolean value
        """
        return self.media_like(media_id, revert=True)
