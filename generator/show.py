from . import settings as SETTINGS
from .episode_source import EpisodeSource
from feedgen.feed import FeedGenerator
from .metadata_sources import EpisodeMetadataSource
from .metadata_sources.SkipEpisode import SkipEpisode
from threading import Thread, BoundedSemaphore, RLock


MAX_CONCURRENT_EPISODE_FEED_WRITERS = 15

class Show:
    def __init__(
            self,
            title: str,
            show_id: int,
            short_description: str =None,
            image: str =None,
            category: str =None,
            sub_category: str =None,
            language: str ="no",
            show_url: str =None,
            editorial_email: str =None,
            technical_email: str =None,
            copyright_: str =None,
            old: bool =False,
            long_description: str =None,
            author: str =None,
            explicit: bool =None,
    ):
        """Initialize a new show with the provided data.

        Args:
            title (str): Name of the show. Obligatory.
            show_id (int): DigAS ID for the show. Obligatory.
            short_description (str): Short description (couple words) describing the show.
                Defaults to something generic.
            image (str): URL for image which will be used for this show. It must be PNG or JPEG, and it must
                be between 1400x1400 and 3000x3000 in resolution. Change the URL if the image changes. Defaults to no
                image.
            category (str): iTunes category for this show. See
                https://help.apple.com/itc/podcasts_connect/#/itc9267a2f12 for available categories. Defaults to no
                category.
            sub_category (str): iTunes sub-category for this show. See
                https://help.apple.com/itc/podcasts_connect/#/itc9267a2f12 for available sub-categories. Defaults to no
                sub-category.
            language (str): Language of this show. Use one of the two-letter values found in
                http://www.loc.gov/standards/iso639-2/php/code_list.php. Default value is in settings.py.
            show_url (str): This show's website. Defaults to whatever default is in settings.py.
            editorial_email (str): Email for whoever is responsible for the content. Default value is in settings.py.
            technical_email (str): Email for whoever is responsible for the technical aspect of the feed, for instance
                the webmaster. Default value is in settings.py.
            copyright_ (str): Information about this show's copyright. Defaults to nothing.
            old (bool): Set to True if there won't be published more podcast episodes for this feed.
            long_description (str): Long description, which is used when you hover the i icon in iTunes. Defaults to
                short_description.
            author (str): Name of the author. Defaults to the title (that is, the show name).
            explicit (bool | None): True if this show is explicit, False if this show is clean, None if it's undecided
                (default).
        """
        self.title = title
        """str: Name of the show."""
        self.show_id = show_id
        """int: DigAS ID for the show."""

        self.short_description = short_description if short_description is not None \
            else SETTINGS.DEFAULT_SHORT_FEED_DESCRIPTION
        """str: Short description (couple words) describing the show."""
        self.long_description = long_description if long_description is not None else short_description
        """str: Long description, which is used when you hover the i icon in iTunes."""
        self.image = image
        """str: URL for image which will be used for this show. It must be PNG or JPEG, and it must
    be between 1400x1400 and 3000x3000 in resolution. Change the URL if the image changes."""
        self.category = category
        """str: iTunes category for this show. See
    https://help.apple.com/itc/podcasts_connect/#/itc9267a2f12 for available categories."""
        self.sub_category = sub_category
        """str: iTunes sub-category for this show. See
    https://help.apple.com/itc/podcasts_connect/#/itc9267a2f12 for available sub-categories."""
        self.language = language
        """str: Language of this show. Use one of the two-letter values found in
    http://www.loc.gov/standards/iso639-2/php/code_list.php."""
        self.show_url = show_url if show_url is not None else SETTINGS.DEFAULT_WEBSITE
        """str: This show's website."""
        self.editorial_email = editorial_email if editorial_email is not None else SETTINGS.DEFAULT_EDITORIAL_EMAIL
        """str: Email for whoever is responsible for the content."""
        self.technical_email = technical_email if technical_email is not None else SETTINGS.DEFAULT_TECHNICAL_EMAIL
        """str: Email for whoever is responsible for the technical aspect of the feed, for instance the webmaster."""
        self.copyright = copyright_
        """str: Information about this show's copyright."""
        self.old = old
        """bool: Set to True if there won't be published more podcast episodes for this feed."""
        self.author = author if author is not None else title
        """str: Name of the author/artist."""
        self.explicit = explicit
        """bool | None: True if this show is explicit, False if this show is clean, None if it's undecided"""

        self.feed = None
        """FeedGenerator: Reference to the FeedGenerator associated with this show."""

        self.write_feed_constraint = BoundedSemaphore(MAX_CONCURRENT_EPISODE_FEED_WRITERS)

    def init_feed(self) -> FeedGenerator:
        feed = FeedGenerator()
        feed.load_extension('podcast', rss=True)

        feed.title(self.title)

        feed.podcast.itunes_subtitle(self.short_description)
        feed.description(self.short_description)
        feed.podcast.itunes_summary(self.long_description)
        if self.image is not None:
            feed.podcast.itunes_image(self.image)

        if self.category is not None:
            if self.sub_category is not None:
                feed.podcast.itunes_category(self.category, self.sub_category)
            else:
                feed.podcast.itunes_category(self.category)

        feed.language(self.language)
        feed.link({'href': self.show_url})
        feed.managingEditor(self.editorial_email)
        feed.webMaster(self.technical_email)
        if self.copyright is not None:
            feed.rights(self.copyright)
        feed.podcast.itunes_complete(self.old)
        feed.podcast.itunes_author(self.author)
        if self.explicit is not None:
            feed.podcast.itunes_explicit(self.explicit)

        self.feed = feed

        return feed

    def add_episodes_to_feed(self, episode_source: EpisodeSource, metadata_sources: list):
        """Add all episodes from the episode_source to this show's feed, populating them with metadata."""
        # Are the metadata sources of the right type?
        for source in metadata_sources:
            assert isinstance(source, EpisodeMetadataSource), "%r is not a subclass of EpisodeMetadataSource." % source

        threads = list()
        feed_access_lock = RLock()
        for episode in episode_source.episode_generator():
            # Let each metadata source provide metadata, if they have it
            for source in metadata_sources:
                if source.accepts(episode):
                    source.populate(episode)
            # Add this episode to the feed
            episode.add_to_feed(self.feed)
            thread = Thread(target=self.write_episode_to_feed,
                            kwargs={'episode': episode, 'feed_access_lock': feed_access_lock, 'fg': self.feed})
            thread.start()
            threads.append(thread)

        # Wait for everyone to finish
        for thread in threads:
            thread.join()

    def write_episode_to_feed(self, episode, feed_access_lock, fg):
        with self.write_feed_constraint:
            try:
                episode.populate_feed_entry()
            except SkipEpisode:
                # Don't include this episode
                with feed_access_lock:
                    episode.remove_from_feed(fg)
