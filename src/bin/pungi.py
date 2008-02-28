#!/usr/bin/python -tt
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os
import pypungi.config
import pypungi.gather
import pypungi.pungi
import yum
import pykickstart.parser
import pykickstart.version
import subprocess

def main():

    config = pypungi.config.Config()

    (opts, args) = get_arguments(config)

    # You must be this high to ride if you're going to do root tasks
    if os.geteuid () != 0 and (opts.do_all or opts.do_buildinstall):
        print >> sys.stderr, "You must run pungi as root"
        return 1
    
    if opts.do_all or opts.do_buildinstall:
        try:
            selinux = subprocess.Popen('/usr/sbin/getenforce', 
                                       stdout=subprocess.PIPE, 
                                       stderr=open('/dev/null', 'w')).communicate()[0].strip('\n')
            if selinux == 'Enforcing':
                print >> sys.stdout, "WARNING: SELinux is enforcing.  This may lead to a compose with selinux disabled."
                print >> sys.stdout, "Consider running with setenforce 0."
        except:
            pass

    # Set up the kickstart parser and pass in the kickstart file we were handed
    ksparser = pykickstart.parser.KickstartParser(pykickstart.version.makeVersion())
    ksparser.readKickstart(opts.config)

    if opts.sourceisos:
        config.set('default', 'arch', 'source')

    for part in ksparser.handler.partition.partitions:
        if part.mountpoint == 'iso':
            config.set('default', 'cdsize', str(part.size))
            
    config.set('default', 'force', str(opts.force))

    # Set up our directories
    if not os.path.exists(config.get('default', 'destdir')):
        try:
            os.makedirs(config.get('default', 'destdir'))
        except OSError, e:
            print >> sys.stderr, "Error: Cannot create destination dir %s" % config.get('default', 'destdir')
            sys.exit(1)
    else:
        print >> sys.stdout, "Warning: Reusing existing destination directory."

    cachedir = config.get('default', 'cachedir')

    if not os.path.exists(cachedir):
        try:
            os.makedirs(cachedir)
        except OSError, e:
            print >> sys.stderr, "Error: Cannot create cache dir %s" % cachedir
            sys.exit(1)

    # Actually do work.
    if not opts.sourceisos:
        if opts.do_all or opts.do_gather:
            mygather = pypungi.gather.Gather(config, ksparser)
            mygather.getPackageObjects()
            mygather.downloadPackages()
            mygather.makeCompsFile()
            if not opts.nosource:
                mygather.getSRPMList()
                mygather.downloadSRPMs()

            del mygather

        mypungi = pypungi.pungi.Pungi(config)

        if opts.do_all or opts.do_createrepo:
           mypungi.doCreaterepo()

        if opts.do_all or opts.do_buildinstall:
           mypungi.doGetRelnotes()
           mypungi.doBuildinstall()

        if opts.do_all or opts.do_createiso:
           mypungi.doCreateIsos(split=opts.nosplitmedia)

    # Do things slightly different for src.
    if opts.sourceisos:
        # we already have all the content gathered
        mypungi = pypungi.pungi.Pungi(config)
        mypungi.topdir = os.path.join(config.get('default', 'destdir'),
                                      config.get('default', 'version'),
                                      config.get('default', 'flavor'),
                                      'source', 'SRPM')
        if opts.do_all or opts.do_createiso:
            mypungi.doCreateIsos(split=opts.nosplitmedia)

    print "All done!"

if __name__ == '__main__':
    from optparse import OptionParser
    import sys
    import time

    today = time.strftime('%Y%m%d', time.localtime())

    def get_arguments(config):
        parser = OptionParser(version="%prog 1.2.8")

        def set_config(option, opt_str, value, parser, config):
            config.set('default', option.dest, value)

        # Pulled in from config file to be cli options as part of pykickstart conversion
        parser.add_option("--name", dest="name", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='the name for your distribution (defaults to "Fedora")')
        parser.add_option("--ver", dest="version", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='the version of your distribution (defaults to datestamp)')
        parser.add_option("--flavor", dest="flavor", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='the flavor of your distribution spin (optional)')
        parser.add_option("--destdir", dest="destdir", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='destination directory (defaults to current directory)')
        parser.add_option("--cachedir", dest="cachedir", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='package cache directory (defaults to /var/cache/pungi)')
        parser.add_option("--bugurl", dest="bugurl", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='the url for your bug system (defaults to http://bugzilla.redhat.com)')
        parser.add_option("--discs", dest="discs", type="string",
          action="callback", callback=set_config, callback_args=(config, ),
          help='the number of discs you want to create (defaults to 1)')
        parser.add_option("--nosource", action="store_true", dest="nosource",
          help='disable gathering of source packages (optional)')
        parser.add_option("--nosplitmedia", action="store_false", dest="nosplitmedia", default=True,
          help='disable creation of split media (optional)')
        parser.add_option("--sourceisos", default=False, action="store_true", dest="sourceisos",
          help='Create the source isos (other arch runs must be done)')
        parser.add_option("--force", default=False, action="store_true",
          help='Force reuse of an existing destination directory (will overwrite files)')

        parser.add_option("-c", "--config", dest="config",
          help='Path to kickstart config file')
        parser.add_option("--all-stages", action="store_true", default=True, dest="do_all",
          help="Enable ALL stages")
        parser.add_option("-G", action="store_true", default=False, dest="do_gather",
          help="Flag to enable processing the Gather stage")
        parser.add_option("-C", action="store_true", default=False, dest="do_createrepo",
          help="Flag to enable processing the Createrepo stage")
        parser.add_option("-B", action="store_true", default=False, dest="do_buildinstall",
          help="Flag to enable processing the BuildInstall stage")
        parser.add_option("-I", action="store_true", default=False, dest="do_createiso",
          help="Flag to enable processing the CreateISO stage")


        (opts, args) = parser.parse_args()
        
        if not opts.config:
            parser.print_help()
            sys.exit(0)
            
        if not config.get('default', 'flavor').isalnum() and not config.get('default', 'flavor') == '':
            print >> sys.stderr, "Flavor must be alphanumeric."
            sys.exit(1)

        if opts.do_gather or opts.do_createrepo or opts.do_buildinstall or opts.do_createiso:
            opts.do_all = False
        return (opts, args)

    main()