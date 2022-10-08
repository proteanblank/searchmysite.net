import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.exceptions import DropItem
from scrapy.http import HtmlResponse, XmlResponse
from bs4 import BeautifulSoup, SoupStrainer
import datetime
from scrapy.utils.log import configure_logging
from scrapy.utils.project import get_project_settings
import logging
import feedparser
from common.utils import extract_domain_from_url, convert_string_to_utc_date, convert_datetime_to_utc_date, get_text

# Solr schema is:
#    <field name="url" type="string" indexed="true" stored="true" required="true" />
#    <field name="domain" type="string" indexed="true" stored="true" required="true" />
#    <field name="is_home" type="boolean" indexed="true" stored="true" /> <!-- true for home page, false for all other pages -->
#    <field name="title" type="text_general" indexed="true" stored="true" multiValued="false" />
#    <field name="author" type="string" indexed="true" stored="true" />
#    <field name="description" type="text_general" indexed="true" stored="true" multiValued="false" />
#    <field name="tags" type="string" indexed="true" stored="true" multiValued="true" />
#    <field name="body" type="text_general" indexed="true" stored="true" multiValued="false" /> <!-- no longer in use -->
#    <field name="content" type="text_general" indexed="true" stored="true" multiValued="false" />
#    <field name="content_type" type="string" indexed="true" stored="true" />
#    <field name="page_type" type="string" indexed="true" stored="true" />
#    <field name="page_last_modified" type="pdate" indexed="true" stored="true" />
#    <field name="published_date" type="pdate" indexed="true" stored="true" />
#    <field name="indexed_date" type="pdate" indexed="true" stored="true" />
#    <field name="date_domain_added" type="pdate" indexed="true" stored="true" /> <!-- only present on pages where is_home=true -->
#    <field name="site_category" type="string" indexed="true" stored="true" /> <!-- same value for every page in a site -->
#    <field name="site_last_modified" type="pdate" indexed="true" stored="true" /> <!-- not currently in use -->
#    <field name="owner_verified" type="boolean" indexed="true" stored="true" /> <!-- same value for every page in a site -->
#    <field name="contains_adverts" type="boolean" indexed="true" stored="true" />
#    <field name="api_enabled" type="boolean" indexed="true" stored="true" /> <!-- only present on pages where is_home=true -->
#    <field name="public" type="boolean" indexed="true" stored="true" /> <!-- same value for every page (false only an option where owner_verified=true) -->
#    <field name="in_web_feed" type="boolean" indexed="true" stored="true" />
#    <field name="rss_feed" type="string" indexed="true" stored="true" /> <!-- no longer in use -->
#    <field name="web_feed" type="string" indexed="true" stored="true" />
#    <field name="language" type="string" indexed="true" stored="true" />
#    <field name="language_primary" type="string" indexed="true" stored="true" />
#    <field name="indexed_inlinks" type="string" indexed="true" stored="true" multiValued="true" />
#    <field name="indexed_inlinks_count" type="pint" indexed="true" stored="true" />
#    <field name="indexed_inlink_domains" type="string" indexed="true" stored="true" multiValued="true" />
#    <field name="indexed_inlink_domains_count" type="pint" indexed="true" stored="true" />
#    <field name="indexed_outlinks" type="string" indexed="true" stored="true" multiValued="true" />

def customparser(response, domain, is_home, domains_for_indexed_links, site_config, common_config):

    configure_logging(get_project_settings())
    logger = logging.getLogger()
    logger.info('Parsing {}'.format(response.url))

    # check for type (this is first because some types might be on the exclude type list and we want to return None so it isn't yielded)
    ctype = response.xpath('//meta[@property="og:type"]/@content').get() # <meta property="og:type" content="..." />
    if not ctype: ctype = response.xpath('//article/@data-post-type').get() # <article data-post-id="XXX" data-post-type="...">
    exclusions = site_config['exclusions']
    if exclusions:
        for exclusion in exclusions:
            if exclusion['exclusion_type'] == 'type':
                if exclusion['exclusion_value'] == ctype:
                    logger.info('Excluding item because type "{}" is on type exclusion list'.format(ctype))
                    return None

    item = {}


    # Attributes set on all TextResponse, i.e. on both HtmlResponse and XmlResponse
    # -----------------------------------------------------------------------------

    # id
    item['id'] = response.url

    # url
    item['url'] = response.url

    # domain
    item['domain'] = domain

    # is_home, i.e. the page is the home page
    if is_home:
        logger.info('Setting home page: {}'.format(response.url))
    item['is_home'] = is_home

    # title
    # XML can have a title tag
    item['title'] = response.xpath('//title/text()').get() # <title>...</title>

    # content_type, e.g. text/html; charset=utf-8
    content_type = None
    content_type_header = response.headers.get('Content-Type')
    if content_type_header:
        content_type = content_type_header.decode('utf-8').split(';')[0]
    item['content_type'] = content_type

    # last_modified_date
    last_modified_date = response.headers.get('Last-Modified')
    if last_modified_date:
        last_modified_date = last_modified_date.decode('utf-8')
        last_modified_date = convert_string_to_utc_date(last_modified_date)
    item['page_last_modified'] = last_modified_date

    # indexed_date
    indexed_date = convert_datetime_to_utc_date(datetime.datetime.now())
    item['indexed_date'] = indexed_date

    # site_category
    item['site_category'] = site_config['site_category']

    # indexed_inlinks
    # i.e. the pages in the search collection on other domains which link to this page
    indexed_inlinks = []
    #logger.info('Processing indexed_inlinks for {}'.format(response.url))
    if response.url in site_config['indexed_inlinks']:
        #logger.info('Found an indexed_inlink: {}'.format(other_config['indexed_inlinks'][response.url]))
        indexed_inlinks = site_config['indexed_inlinks'][response.url]
    item['indexed_inlinks'] = indexed_inlinks

    # indexed_inlinks_count
    if len(indexed_inlinks) > 0:
        item['indexed_inlinks_count'] = len(indexed_inlinks)
    else:
        item['indexed_inlinks_count'] = None

    # indexed_inlink_domains
    indexed_inlink_domains = []
    if indexed_inlinks:
        for indexed_inlink in indexed_inlinks:
            indexed_inlink_domain = extract_domain_from_url(indexed_inlink, common_config['domains_allowing_subdomains'])
            if indexed_inlink_domain not in indexed_inlink_domains:
                indexed_inlink_domains.append(indexed_inlink_domain)
    item['indexed_inlink_domains'] = indexed_inlink_domains

    # indexed_inlink_domains_count
    if len(indexed_inlink_domains) > 0:
        item['indexed_inlink_domains_count'] = len(indexed_inlink_domains)
    else:
        item['indexed_inlink_domains_count'] = None

    # indexed_outlinks
    # i.e. the links in this page to pages in the search collection on other domains
    indexed_outlinks = []
    if domains_for_indexed_links:
        extractor = LinkExtractor(allow_domains=domains_for_indexed_links) # i.e. external links
        links = extractor.extract_links(response)
        for link in links:
            indexed_outlinks.append(link.url)
    item['indexed_outlinks'] = indexed_outlinks

    # owner_verified
    # This used to be an explicit field, but now is set by search_my_site_scheduler.py when tier = 3
    owner_verified = False
    if site_config['owner_verified'] == True: 
        owner_verified = True
    item['owner_verified'] = owner_verified

    # api_enabled & date_domain_added
    # Now site in pipelines.py if is_home == True

    # public - should always be true, except in rare cases where owner_verified=true (but not checking to enforce)
    include_in_public_search = True
    if site_config['include_in_public_search'] == False:
        include_in_public_search = False
    item['public'] = include_in_public_search

    # web_feed - True if the page is in a web feed (RSS or Atom), False otherwise
    if response.url in site_config['feed_links']:
        item['in_web_feed'] = True
        item['web_feed'] = site_config['web_feed']
    else:
        item['in_web_feed'] = False


    # Attributes set only on HtmlResponse
    # -----------------------------------

    if isinstance(response, HtmlResponse):

        # page_type (value obtained at the start in case there was a page type exclusion) 
        item['page_type'] = ctype

        # author
        item['author'] = response.xpath('//meta[@name="author"]/@content').get() # <meta name="author" content="...">

        # description
        description = response.xpath('//meta[@name="description"]/@content').get() # <meta name="description" content="...">
        if not description: description = response.xpath('//meta[@property="og:description"]/@content').get() # <meta property="og:description" content="..." />
        item['description'] = description

        # tags
        # Should be comma delimited as per https://www.w3.org/TR/2011/WD-html5-author-20110809/the-meta-element.html
        # but unfortunately some sites are space delimited
        tags = response.xpath('//meta[@name="keywords"]/@content').get() # <meta name="keywords" content="...">
        if not tags: tags = response.xpath('//meta[@property="article:tag"]/@content').get() # <meta property="article:tag" content="..."/>
        tag_list = []
        if tags:
            if tags.count(',') == 0 and tags.count(' ') > 1: # no commas and more than one space
                for tag in tags.split(" "):
                    tag_list.append(tag.lstrip())
            else:
                for tag in tags.split(","):
                    tag_list.append(tag.lstrip())
        item['tags'] = tag_list

        # content
        only_body = SoupStrainer('body')
        body_html = BeautifulSoup(response.text, 'lxml', parse_only=only_body)
        for non_content in body_html(["nav", "header", "footer"]): # Remove nav, header, and footer tags and their contents
            non_content.decompose()
        main_html = body_html.find('main')
        article_html = body_html.find('article')
        if main_html:
            content_text = get_text(main_html)
        elif article_html:
            content_text = get_text(article_html)
        else:
            content_text = get_text(body_html)
        item['content'] = content_text

        # published_date
        published_date = response.xpath('//meta[@property="article:published_time"]/@content').get()
        if not published_date: published_date = response.xpath('//meta[@name="dc.date.issued"]/@content').get()
        if not published_date: published_date = response.xpath('//meta[@itemprop="datePublished"]/@content').get()
        published_date = convert_string_to_utc_date(published_date)
        item['published_date'] = published_date

        # contains_adverts
        # Just looks for Google Ads at the moment
        contains_adverts = False # assume a page has no adverts unless proven otherwise
        if response.xpath('//ins[contains(@class,"adsbygoogle")]') != []: contains_adverts = True
        item['contains_adverts'] = contains_adverts

        # language, e.g. en-GB
        language = response.xpath('/html/@lang').get()
        #if language: language = language.lower() # Lowercasing to prevent facetted nav thinking e.g. en-GB and en-gb are different
        item['language'] = language

        # language_primary, e.g. en
        language_primary = None
        if language:
            language_primary = language[:2] # First two characters, e.g. en-GB becomes en
        item['language_primary'] = language_primary

    elif isinstance(response, XmlResponse):

        # For XML this will record the rood node name 
        item['page_type'] = response.xpath('name(/*)').get()

        d = feedparser.parse(response.text)
        entries = d.entries
        version = None
        if entries:
            version = d.version
            item['is_web_feed'] = True


    return item
