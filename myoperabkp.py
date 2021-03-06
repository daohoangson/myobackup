#!/usr/bin/env python2.7
# encoding: utf-8
"""
myoperabkp.py

Created by Karl Dubost on 2013-01-24.
Copyright (c) 2013 Grange. All rights reserved.
see LICENSE.TXT
"""

import argparse
import sys
import requests
import logging
from lxml import etree
from urlparse import urljoin
import time
import string
import urllib2
import imghdr
import os
import errno
from string import Template
import fnmatch
import re
import HTMLParser

# variables
myopath = "http://my.opera.com/%s/archive/"


def getcontentbinary(uri):
    """Given a uri, parse an html document"""
    headers = {'User-Agent': "MyOpera-Backup/1.0"}

    cachepath = "cache/%s" % (re.sub(r"[^a-zA-Z0-9\/\-\_\.]", "", uri))
    if (cachepath[-1] == "/"):
        cachepath += "index.html"

    if (os.path.exists(cachepath) and os.path.getsize(cachepath) > 0):
        with open(cachepath, "rb") as cachefile:
            responsedata = cachefile.read()
        logging.info("read cache %s for %s" % (cachepath, uri))
    else:
        try:
            r = requests.get(uri, headers=headers)
            responsedata = r.content

            mkdir(os.path.dirname(cachepath))
            with open(cachepath, "wb") as cachefile:
                cachefile.write(responsedata)
            logging.info("request %s (saved to %s)" % (uri, cachepath))
        except requests.exceptions.ConnectionError as exc:
            responsedata = b""
            logging.error("give up %s (%s)" % (uri, exc))

    return responsedata


def getcontent(uri):
    return getcontentbinary(uri)


def getpostcontent(uri):
    "return the elements of a blog post: content, title, date, imglist, taglist"
    myparser = etree.HTMLParser(encoding="utf-8")
    posthtml = getcontent(uri)
    tree = etree.HTML(posthtml, parser=myparser)
    # grab the title/date of the blog post. There are two forms:
    # idpost - http://my.opera.com/{username}/blog/?id={id}
    # <h2 class="title"><a href="/{username}/blog/show.dml/{id}">FooText</a></h2>
    # <p class="postdate"><a href="/{username}/blog/show.dml/{id}" title="Permanent link">Wednesday, October 8, 2008 4:19:29 AM</a></p>
    # prosepost
    # <h2 class="title">FooText</h2>
    # <p class="postdate">Thursday, October 16, 2008 11:12:34 PM</p>
    idpost = uri.partition('?id=')[2]
    if idpost:
        title = tree.xpath('//div[@id="firstpost"]//h2[@class="title"]/a/text()')
        postdate = tree.xpath('//div[@id="firstpost"]//p[@class="postdate"]/a/text()')
    else:
        title = tree.xpath('//div[@id="firstpost"]//h2[@class="title"]/text()')
        postdate = tree.xpath('//div[@id="firstpost"]//p[@class="postdate"]/text()')
    content = tree.xpath('//div[@id="firstpost"]//div[@class="content"]')
    imageslist = tree.xpath('//div[@id="firstpost"]//div[@class="content"]//img/@src')
    taglist = tree.xpath('//div[@id="firstpost"]//a[@rel="tag"]/text()')

    commentDivs = tree.xpath('//div[@class="comments"]/div')
    comments = []
    for commentDiv in commentDivs:
        commentDiv = etree.HTML(etree.tostring(commentDiv), parser=myparser)

        commentText = commentDiv.xpath('//div[@class="text"]/text()')
        if len(commentText) < 1:
            continue

        parsedId = '' # commentDiv.get('id')

        parsedDate = commentDiv.xpath('//span[@class="comment-date"]/text()')
        if len(parsedDate) < 1:
            continue

        match = re.search("^([^:]+) writes:([^$]+)", commentText[0])
        if match:
            parsedAuthor = match.group(1)
            parsedContent = match.group(2).strip()
            comments.append(dict([
                ("id", parsedId),
                ("date", parsedDate[0].strip()),
                ("author", parsedAuthor),
                ("content", parsedContent)]))

    return dict([
        ("uri", uri),
        ("title", title),
        ("date", postdate),
        ("html", etree.tostring(content[0])),
        ("imglist", imageslist),
        ("taglist", taglist),
        ("comments", comments)])


def mkdir(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def pathdate(datetext):
    """return a path according to the date text
    datetext: Sunday, March 30, 2008 6:32:55 PM
    pathdate: /2008/03/30/"""
    datestruct = time.strptime(datetext, '%A, %B %d, %Y %I:%M:%S %p')
    return time.strftime("/%Y/%m/%d/", datestruct)


def archiveimage(imguri, localpostpath):
    "save the image locally"
    # read image data
    imagedata = getcontentbinary(imguri)
    # take the last part of the path after "/"
    imagename = string.rsplit(imguri, "/", 1)[-1:][0]
    # take the last part of the string after "."
    extension = string.rsplit(imagename, ".", 1)[-1:][0]
    # if the extension not in common format, what is it?
    # TOFIX: corner cases
    # foo.bar (but really foo.bar.png)
    # foo     (but really foo.png)
    # foo.svg
    if extension.lower() not in ["jpg", "png", "gif"]:
        imagetype = imghdr.what(None, imagedata[:32])
        if imagetype == "jpeg":
            extension = "jpg"
        else:
            extension = imagetype
        filename = "%s.%s" % (imagename, extension)
    else:
        filename = imagename
    fullpath = "%s%s" % (localpostpath, filename)
    # save the image
    with open(fullpath, 'wb') as imagefile:
        imagefile.write(imagedata)
        logging.info("created image at %s" % (fullpath))
    return filename


def changeimglink(imguri, newloc, blogposthtml):
    "change all URI to images by the local path"
    # rewrite the img src to the new destination
    blogposthtml = blogposthtml.replace(imguri, newloc)
    return blogposthtml


def archivepost(blogpost, localpostpath):
    "given the blogpost, archive it locally"
    extension = "html"
    posturi = blogpost['uri']
    postname = string.rsplit(posturi, "/", 1)[-1:][0]
    # to cope with idpost type, aka postname = ?id={id}
    if postname.startswith('?id='):
        postname = postname[4:]
    postdate = blogpost['date'][0]
    posttitle = blogpost['title'][0]
    postcontent = blogpost['html']
    with open('posttemplate.html', 'r') as source:
        t = Template(source.read())
        result = t.substitute(date=postdate, title=posttitle, content=postcontent)
    filename = "%s.%s" % (postname, extension)
    fullpath = "%s%s" % (localpostpath, filename)
    with open(fullpath, 'w') as blogfile:
        blogfile.write(result.encode('utf-8'))
        logging.info("created blogpost at %s" % (fullpath))


def blogpostlist(useruri):
    "return a list of blog posts URI for a given username"
    postlist = []
    myparser = etree.HTMLParser(encoding="utf-8")
    archivehtml = getcontent(useruri)
    tree = etree.HTML(archivehtml, parser=myparser)
    # Check for both types of MyOpera archive
    navlinks = tree.xpath('(//p[@class="pagenav"] | //div[@class="month"]//li)//a/@href')
    # Remove the last item of the list which is the next link
    navlinks.pop()
    # create a sublist of archives links
    archlinks = fnmatch.filter(navlinks, '?startidx=*')
    # Insert the first page of the archive at the beginning
    archlinks.insert(0, useruri)
    # making full URI
    archlinks = [urljoin(useruri, archivelink) for archivelink in archlinks]
    # we go through all the list
    for archivelink in archlinks:
        archtml = getcontent(archivelink)
        tree = etree.HTML(archtml, parser=myparser)
        links = tree.xpath('//div[@id="arc"]//li//a/@href')
        # Getting the links for all the archive page only!
        for link in links:
            postlist.append(urljoin(useruri, link))
    return postlist


def createwxritem(blogpost, WP, CONTENT):
    "Create an lxml element (item) for each item post for WXR"

    hp = HTMLParser.HTMLParser()
    item = etree.Element('item')
    etree.SubElement(item, 'title').text = blogpost['title'][0]
    etree.SubElement(item, WP + 'status').text = 'publish'
    etree.SubElement(item, WP + 'post_type').text = 'post'
    etree.SubElement(item, CONTENT + "encoded").text = etree.CDATA(hp.unescape(blogpost['html']))
    # MyOpera date format is "Monday, December 10, 2012 6:35:49 AM"
    # pubDate format is "Thu, 24 Sep 2012 01:40:01 +0000"
    datestruct = time.strptime(blogpost['date'][0], '%A, %B %d, %Y %I:%M:%S %p')
    pubdate = time.strftime("%a, %d %b %Y %T", datestruct)
    isodate = time.strftime("%Y-%m-%d %T", datestruct)
    etree.SubElement(item, "pubDate").text = pubdate + ' +0000'
    etree.SubElement(item, WP + "post_date").text = isodate
    etree.SubElement(item, WP + "post_date_gmt").text = isodate
    # Add an element for each tag
    for tag in blogpost['taglist']:
        tag_element = etree.SubElement(item, "category")
        tag_element.text = etree.CDATA(tag)
        tag_element.set('domain', 'post_tag')
        tag_element.set('nicename', tag)

    for comment in blogpost['comments']:
        commentDateStruct = time.strptime(comment['date'], '%A, %B %d, %Y %I:%M:%S %p')
        commentDate = time.strftime("%Y-%m-%d %T", commentDateStruct)

        commentId = comment['id']
        if len(commentId) == 0:
            commentId = '%d' % (time.mktime(commentDateStruct))

        comment_element = etree.SubElement(item, WP + "comment")
        etree.SubElement(comment_element, WP + "comment_id").text = etree.CDATA(commentId)
        etree.SubElement(comment_element, WP + "comment_date").text = etree.CDATA(commentDate)
        etree.SubElement(comment_element, WP + "comment_date_gmt").text = etree.CDATA(commentDate)
        etree.SubElement(comment_element, WP + "comment_author").text = etree.CDATA(comment['author'])
        etree.SubElement(comment_element, WP + "comment_content").text = etree.CDATA(comment['content'])
        etree.SubElement(comment_element, WP + "comment_approved").text = etree.CDATA(str(1))

    return item


def createwxr(blogposts, archivepath):
    "Create a WordPress Extended RSS (WXR) file"
    # WXR namespaces
    NS_EXCERPT = "http://wordpress.org/export/1.2/excerpt/"
    NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
    NS_WFW = "http://wellformedweb.org/CommentAPI/"
    NS_DC = "http://purl.org/dc/elements/1.1/"
    NS_WP = "http://wordpress.org/export/1.2/"
    EXCERPT = "{%s}" % NS_EXCERPT
    CONTENT = "{%s}" % NS_CONTENT
    WFW = "{%s}" % NS_WFW
    DC = "{%s}" % NS_DC
    WP = "{%s}" % NS_WP
    NSMAP = {
        'excerpt': NS_EXCERPT,
        'content': NS_CONTENT,
        'wfw': NS_WFW,
        'dc': NS_DC,
        'wp': NS_WP,
    }
    # Generate the WordPress XML document
    root = etree.Element('rss', attrib={'version': '2.0'}, nsmap=NSMAP)
    channel = etree.SubElement(root, 'channel')
    wxr_version = etree.SubElement(channel, WP + 'wxr_version').text = "1.2"
    for blogpost in blogposts:
        item = createwxritem(blogpost, WP, CONTENT)
        channel.append(item)
    # Write to file:
    tree = etree.ElementTree(root)
    tree.write(archivepath + os.sep + 'output.xml', encoding='utf-8', pretty_print=True, xml_declaration=True)


def main():
    logging.basicConfig(filename='log-myopera.txt',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s')

    # Parsing the cli
    parser = argparse.ArgumentParser(
        description="Export html content from my.opera")
    parser.add_argument(
        '-u',
        action='store',
        dest="username",
        required=True,
        help='username we want to backup')
    parser.add_argument(
        '-o',
        action='store',
        dest="archivepath",
        default="myoarchive",
        help='local path where the backup will be kept')

    args = parser.parse_args()
    username = args.username
    archivepath = args.archivepath
    useruri = myopath % (username)
    print 'Getting blog posts for ' + username + '. This may take a while...'
    blogposts = []
    # return the list of all blog posts URI
    everylinks = blogpostlist(useruri)
    print "We grabbed the list of all URIs for %s" % (username)
    print "Let's save them locally in %s" % (archivepath)
    # iterate over all blogposts
    for blogpostlink in everylinks:
        # get the data about the blog post & add to blogposts list
        blogpost = getpostcontent(blogpostlink)
        blogposts.append(blogpost)
        # Convert the date of the blog post to a path
        blogpostdate = blogpost['date'][0]
        blogpostdatepath = pathdate(blogpostdate)
        # Create the local path where the blog post will be archived
        localpostpath = "%s%s" % (archivepath, blogpostdatepath)
        mkdir(localpostpath)
        # Archive images
        imgurilist = blogpost['imglist']
        if imgurilist:
            # if not empty list, archive images
            for imguri in imgurilist:
                imagename = archiveimage(imguri, localpostpath)
                newimageloc = "%s%s" % (blogpostdatepath, imagename)
                blogpost['html'] = changeimglink(imguri, newimageloc, blogpost['html'])
            # change the links in the blog post
        archivepost(blogpost, localpostpath)
        print "* " + blogpost['title'][0]
    # Create WXR file for WordPress
    createwxr(blogposts, archivepath)

if __name__ == "__main__":
    sys.exit(main())
