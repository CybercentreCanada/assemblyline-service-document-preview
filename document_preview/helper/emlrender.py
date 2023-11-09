#!/usr/bin/python3
#
# api.py - Flask REST API to render EML files
#
# Author: Xavier Mertens <xavier@rootshell.be>
# Copyright: GPLv3 (http://gplv3.fsf.org)
# Fell free to use the code, but please share the changes you've made
#
# Todo
# - "offline" mode when rendering HTML code
#

import base64
import email
import email.header
import os
import quopri
import sys
from tempfile import NamedTemporaryFile

import regex

try:
    import imgkit
except:
    print('[ERROR] imgkit module not installed ("pip install imgkit")')
    sys.exit(1)

try:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 2147483647
except:
    print('[ERROR] pillow module not installed ("pip install pillow")')
    sys.exit(1)

__author__ = "Xavier Mertens"
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Xavier Mertens"
__email__ = "xavier@erootshell.be"
__name__ = "EMLRender"

textTypes = ["text/plain", "text/html"]
imageTypes = ["image/gif", "image/jpeg", "image/png"]


def appendImages(images):
    bgColor = (255, 255, 255)
    widths, heights = zip(*(i.size for i in images))

    new_width = max(widths)
    new_height = sum(heights)
    new_im = Image.new("RGB", (new_width, new_height), color=bgColor)
    offset = 0
    for im in images:
        # x = int((new_width - im.size[0])/2)
        x = 0
        new_im.paste(im, (x, offset))
        offset += im.size[1]
    return new_im


def processEml(data, output_dir, logger, load_ext_images=False, load_images=False):
    """
    Process the email (bytes), extract MIME parts and useful headers.
    Generate a PNG picture of the mail
    """
    msg = email.message_from_bytes(data)
    try:
        decode = email.header.decode_header(msg["Date"])[0]
        dateField = str(decode[0])
    except:
        dateField = "&lt;Unknown&gt;"
    logger.info("Date: %s" % dateField)

    try:
        decode = email.header.decode_header(msg["From"])[0]
        fromField = str(decode[0])
    except:
        fromField = "&lt;Unknown&gt;"
    logger.info("From: %s" % fromField)
    fromField = fromField.replace("<", "&lt;").replace(">", "&gt;")

    try:
        decode = email.header.decode_header(msg["To"])[0]
        toField = str(decode[0])
    except:
        toField = "&lt;Unknown&gt;"
    logger.info("To: %s" % toField)
    toField = toField.replace("<", "&lt;").replace(">", "&gt;")

    try:
        decode = email.header.decode_header(msg["Subject"])[0]
        subjectField = str(decode[0])
    except:
        subjectField = "&lt;Unknown&gt;"
    logger.info("Subject: %s" % subjectField)
    subjectField = subjectField.replace("<", "&lt;").replace(">", "&gt;")

    try:
        decode = email.header.decode_header(msg["Message-Id"])[0]
        idField = str(decode[0])
    except:
        idField = "&lt;Unknown&gt;"
    logger.info("Message-Id: %s" % idField)
    idField = idField.replace("<", "&lt;").replace(">", "&gt;")

    imgkitOptions = {"load-error-handling": "skip", "quiet": None}
    if not load_ext_images:
        imgkitOptions.update({"no-images": None, "disable-javascript": None})
    # imgkitOptions.update({ 'quiet': None })
    imagesList = []

    # Build a first image with basic mail details
    headers = """
    <table width="100%%">
      <tr><td align="right"><b>Date:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>From:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>To:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>Subject:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>Message-Id:</b></td><td>%s</td></tr>
    </table>
    <hr></p>
    """ % (
        dateField,
        fromField,
        toField,
        subjectField,
        idField,
    )
    try:
        header_path = NamedTemporaryFile(suffix=".png").name
        imgkit.from_string(headers, header_path, options=imgkitOptions)
        logger.info("Created headers %s" % header_path)
        imagesList.append(header_path)
    except Exception as e:
        logger.warning(f"Creation of headers failed: {e}")

    #
    # Main loop - process the MIME parts
    #
    for part in msg.walk():
        mimeType = part.get_content_type()
        if part.is_multipart():
            logger.info("Multipart found, continue")
            continue

        logger.info("Found MIME part: %s" % mimeType)
        if mimeType in textTypes:
            try:
                # Fix formatting
                payload = part.get_payload(decode=True)
                payload = regex.sub(rb"(\r\n){1,}", b"\r\n", payload)
                payload = payload.replace(b"\r\n", b"<br>")
                payload = regex.sub(rb"(<br> ){2,}", b"<br><br>", payload)
                payload = quopri.decodestring(payload).decode("utf-8", errors="ignore")
            except Exception as e:
                payload = str(quopri.decodestring(part.get_payload(decode=True)))[2:-1]

            # # Cleanup dirty characters
            # dirtyChars = ['\n', '\\n', '\t', '\\t', '\r', '\\r']
            # for char in dirtyChars:
            #     payload = payload.replace(char, '')

            try:
                payload_path = NamedTemporaryFile(suffix=".png").name
                imgkit.from_string(payload, payload_path, options=imgkitOptions)
                logger.info("Decoded %s" % payload_path)
                imagesList.append(payload_path)
            except Exception as e:
                logger.warning(f"Decoding this MIME part returned error: {e}")

        elif mimeType in imageTypes and load_images:
            payload = part.get_payload(decode=False)
            payload_path = NamedTemporaryFile(suffix=".png").name
            imgdata = base64.b64decode(payload)
            try:
                with open(payload_path, "wb") as f:
                    f.write(imgdata)
                logger.info("Decoded %s" % payload_path)
                imagesList.append(payload_path)
            except Exception as e:
                logger.warning(f"Decoding this MIME part returned error: {e}")

    resultImage = os.path.join(output_dir, "output.png")
    if len(imagesList) > 0:
        images = list(map(Image.open, imagesList))
        combo = appendImages(images)
        combo.save(resultImage)
        # Clean up temporary images
        for i in imagesList:
            os.remove(i)
        return resultImage
    else:
        return False
