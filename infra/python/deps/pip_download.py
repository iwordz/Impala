#!/usr/bin/python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# Implement the basic 'pip download' functionality in a way that gives us more control
# over which archive type is downloaded and what post-download steps are executed.
# This script requires Python 2.6+.

import hashlib
import os
import os.path
import re
import sys
from random import randint
from time import sleep
from urllib import urlopen, FancyURLopener

NUM_DOWNLOAD_ATTEMPTS = 8

PYPI_MIRROR = os.environ.get('PYPI_MIRROR', 'https://pypi.python.org')

# The requirement files that list all of the required packages and versions.
REQUIREMENTS_FILES = ['requirements.txt', 'stage2-requirements.txt',
                      'compiled-requirements.txt', 'kudu-requirements.txt',
                      'adls-requirements.txt']


def check_digest(filename, algorithm, expected_digest):
  try:
    supported_algorithms = hashlib.algorithms_available
  except AttributeError:
    # Fallback to hardcoded set if hashlib.algorithms_available doesn't exist.
    supported_algorithms = set(['md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512'])
  if algorithm not in supported_algorithms:
    print 'Hash algorithm {0} is not supported by hashlib'.format(algorithm)
    return False
  h = hashlib.new(algorithm)
  h.update(open(filename).read())
  actual_digest = h.hexdigest()
  return actual_digest == expected_digest


def retry(func):
  '''Retry decorator.'''

  def wrapper(*args, **kwargs):
    for try_num in xrange(NUM_DOWNLOAD_ATTEMPTS):
      if try_num > 0:
        sleep_len = randint(5, 10 * 2 ** try_num)
        print 'Sleeping for {0} seconds before retrying'.format(sleep_len)
        sleep(sleep_len)
      try:
        result = func(*args, **kwargs)
        if result:
          return result
      except Exception as e:
        print e
    print 'Download failed after several attempts.'
    sys.exit(1)

  return wrapper

def get_package_info(pkg_name, pkg_version):
  '''Returns the file name, path, hash algorithm and digest of the package.'''
  # We store the matching result in the candidates list instead of returning right away
  # to sort them and return the first value in alphabetical order. This ensures that the
  # same result is always returned even if the ordering changed on the server.
  candidates = []
  url = '{0}/simple/{1}/'.format(PYPI_MIRROR, pkg_name)
  print 'Getting package info from {0}'.format(url)
  # The web page should be in PEP 503 format (https://www.python.org/dev/peps/pep-0503/).
  # We parse the page with regex instead of an html parser because that requires
  # downloading an extra package before running this script. Since the HTML is guaranteed
  # to be formatted according to PEP 503, this is acceptable.
  pkg_info = urlopen(url).read()
  regex = r'<a .*?href=\".*?packages/(.*?)#(.*?)=(.*?)\".*?>(.*?)<\/a>'
  for match in re.finditer(regex, pkg_info):
    path = match.group(1)
    hash_algorithm = match.group(2)
    digest = match.group(3)
    file_name = match.group(4)
    # Make sure that we consider only non Wheel archives, because those are not supported.
    if (file_name.endswith('-{0}.tar.gz'.format(pkg_version)) or
        file_name.endswith('-{0}.tar.bz2'.format(pkg_version)) or
        file_name.endswith('-{0}.zip'.format(pkg_version))):
      candidates.append((file_name, path, hash_algorithm, digest))
  if not candidates:
    print 'Could not find archive to download for {0} {1}'.format(pkg_name, pkg_version)
    return (None, None, None, None)
  return sorted(candidates)[0]

@retry
def download_package(pkg_name, pkg_version):
  file_name, path, hash_algorithm, expected_digest = get_package_info(pkg_name,
      pkg_version)
  if not file_name:
    return False
  if os.path.isfile(file_name) and check_digest(file_name, hash_algorithm,
      expected_digest):
    print 'File with matching digest already exists, skipping {0}'.format(file_name)
    return True
  downloader = FancyURLopener()
  pkg_url = '{0}/packages/{1}'.format(PYPI_MIRROR, path)
  print 'Downloading {0} from {1}'.format(file_name, pkg_url)
  downloader.retrieve(pkg_url, file_name)
  if check_digest(file_name, hash_algorithm, expected_digest):
    return True
  else:
    print 'Hash digest check failed in file {0}.'.format(file_name)
    return False

def main():
  if len(sys.argv) > 1:
    _, pkg_name, pkg_version = sys.argv
    download_package(pkg_name, pkg_version)
    return

  for requirements_file in REQUIREMENTS_FILES:
    # If the package name and version are not specified in the command line arguments,
    # download the packages that in requirements.txt.
    f = open(requirements_file, 'r')
    try:
      # requirements.txt follows the standard pip grammar.
      for line in f:
        # A hash symbol ("#") represents a comment that should be ignored.
        hash_index = line.find('#')
        if hash_index != -1:
          line = line[:hash_index]
        # A semi colon (";") specifies some additional condition for when the package
        # should be installed (for example a specific OS). We can ignore this and download
        # the package anyways because the installation script(bootstrap_virtualenv.py) can
        # take it into account.
        semi_colon_index = line.find(';')
        if semi_colon_index != -1:
          line = line[:semi_colon_index]
        l = line.strip()
        if len(l) > 0:
          pkg_name, pkg_version = l.split('==')
          download_package(pkg_name.strip(), pkg_version.strip())
    finally:
      f.close()

if __name__ == '__main__':
  main()
