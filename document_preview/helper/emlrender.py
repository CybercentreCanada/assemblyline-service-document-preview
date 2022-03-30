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

import os
import sys
import email
import email.header
import quopri
import hashlib
import base64
import regex

try:
    import imgkit
except:
    print('[ERROR] imgkit module not installed ("pip install imgkit")')
    sys.exit(1)

try:
    from PIL import Image
except:
    print('[ERROR] pillow module not installed ("pip install pillow")')
    sys.exit(1)

__author__ = "Xavier Mertens"
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Xavier Mertens"
__email__ = "xavier@erootshell.be"
__name__ = "EMLRender"

textTypes = ['text/plain', 'text/html']
imageTypes = ['image/gif', 'image/jpeg', 'image/png']


def appendImages(images):
    bgColor = (255, 255, 255)
    widths, heights = zip(*(i.size for i in images))

    new_width = max(widths)
    new_height = sum(heights)
    new_im = Image.new('RGB', (new_width, new_height), color=bgColor)
    offset = 0
    for im in images:
        # x = int((new_width - im.size[0])/2)
        x = 0
        new_im.paste(im, (x, offset))
        offset += im.size[1]
    return new_im


def processEml(data, dumpDir, logger):
    '''
    Process the email (bytes), extract MIME parts and useful headers.
    Generate a PNG picture of the mail
    '''
    msg = email.message_from_bytes(data)
    try:
        decode = email.header.decode_header(msg['Date'])[0]
        dateField = str(decode[0])
    except:
        dateField = '&lt;Unknown&gt;'
    logger.info('Date: %s' % dateField)

    try:
        decode = email.header.decode_header(msg['From'])[0]
        fromField = str(decode[0])
    except:
        fromField = '&lt;Unknown&gt;'
    logger.info('From: %s' % fromField)
    fromField = fromField.replace('<', '&lt;').replace('>', '&gt;')

    try:
        decode = email.header.decode_header(msg['To'])[0]
        toField = str(decode[0])
    except:
        toField = '&lt;Unknown&gt;'
    logger.info('To: %s' % toField)
    toField = toField.replace('<', '&lt;').replace('>', '&gt;')

    try:
        decode = email.header.decode_header(msg['Subject'])[0]
        subjectField = str(decode[0])
    except:
        subjectField = '&lt;Unknown&gt;'
    logger.info('Subject: %s' % subjectField)
    subjectField = subjectField.replace('<', '&lt;').replace('>', '&gt;')

    try:
        decode = email.header.decode_header(msg['Message-Id'])[0]
        idField = str(decode[0])
    except:
        idField = '&lt;Unknown&gt;'
    logger.info('Message-Id: %s' % idField)
    idField = idField.replace('<', '&lt;').replace('>', '&gt;')

    imgkitOptions = {'load-error-handling': 'skip'}
    # imgkitOptions.update({ 'quiet': None })
    imagesList = []
    attachments = []

    # Build a first image with basic mail details
    headers = '''
    <table width="100%%">
      <tr><td align="right"><b>Date:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>From:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>To:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>Subject:</b></td><td>%s</td></tr>
      <tr><td align="right"><b>Message-Id:</b></td><td>%s</td></tr>
    </table>
    <hr></p>
    ''' % (dateField, fromField, toField, subjectField, idField)
    m = hashlib.md5()
    m.update(headers.encode('utf-8'))
    imagePath = f'output_{m.hexdigest()}.png'
    try:
        imgkit.from_string(headers, dumpDir + '/' + imagePath, options=imgkitOptions)
        logger.info('Created headers %s' % imagePath)
        imagesList.append(dumpDir + '/' + imagePath)
    except:
        logger.warning('Creation of headers failed')

    #
    # Main loop - process the MIME parts
    #
    for part in msg.walk():
        mimeType = part.get_content_type()
        if part.is_multipart():
            logger.info('Multipart found, continue')
            continue

        logger.info('Found MIME part: %s' % mimeType)
        if mimeType in textTypes:
            try:
                # Fix formatting
                payload = part.get_payload(decode=True)
                payload = regex.sub(rb"(\r\n){1,}", b"\r\n", payload)
                payload = payload.replace(b"\r\n", b'<br>')
                payload = regex.sub(rb"(<br> ){2,}", b'<br><br>', payload)
                payload = quopri.decodestring(payload).decode('utf-8', errors="ignore")
            except Exception as e:
                payload = str(quopri.decodestring(part.get_payload(decode=True)))[2:-1]

            # # Cleanup dirty characters
            # dirtyChars = ['\n', '\\n', '\t', '\\t', '\r', '\\r']
            # for char in dirtyChars:
            #     payload = payload.replace(char, '')

            # Generate MD5 hash of the payload
            m = hashlib.md5()
            m.update(payload.encode('utf-8'))
            imagePath = f'output_{m.hexdigest()}.png'
            try:
                imgkit.from_string(payload, dumpDir + '/' + imagePath, options=imgkitOptions)
                logger.info('Decoded %s' % imagePath)
                imagesList.append(dumpDir + '/' + imagePath)
            except Exception as e:
                logger.warning(f'Decoding this MIME part returned error: {e}')
        elif mimeType in imageTypes:
            payload = part.get_payload(decode=False)
            imgdata = base64.b64decode(payload)
            # Generate MD5 hash of the payload
            m = hashlib.md5()
            m.update(payload.encode('utf-8'))
            imagePath = m.hexdigest() + '.' + mimeType.split('/')[1]
            try:
                with open(dumpDir + '/' + imagePath, 'wb') as f:
                    f.write(imgdata)
                logger.info('Decoded %s' % imagePath)
                imagesList.append(dumpDir + '/' + imagePath)
            except Exception as e:
                logger.warning(f'Decoding this MIME part returned error: {e}')
        else:
            fileName = part.get_filename()
            if not fileName:
                fileName = "Unknown"
            attachments.append("%s (%s)" % (fileName, mimeType))
            logger.info('Skipped attachment %s (%s)' % (fileName, mimeType))

    resultImage = dumpDir + '/' + 'output.png'
    if len(imagesList) > 0:
        images = list(map(Image.open, imagesList))
        combo = appendImages(images)
        combo.save(resultImage)
        # Clean up temporary images
        for i in imagesList:
            os.remove(i)
        return(resultImage)
    else:
        return(False)
