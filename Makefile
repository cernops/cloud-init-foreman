PACKAGE_NAME=cloud-init-foreman
TARBALL=$(PACKAGE_NAME).tar.gz
SOURCES=cc_foreman.py cloud-init-foreman.spec
.PHONY: clean

pkg: 
	tar -czf $(TARBALL)  $(SOURCES)

rpm: pkg
	rpmbuild -ta $(TARBALL)

clean:
	rm -rf $(TARBALL)

