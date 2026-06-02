[![No Maintenance Intended](http://unmaintained.tech/badge.svg)](http://unmaintained.tech/)

PyPodio
=====

Python wrapper for the Podio API.

Install
-------

Dependencies

* httplib2

This copy is vendored inside the cli-tools repository and is installed through
the parent `podio` tool's local path dependency.


Example
-------

    from pypodio2 import api
    from client_settings import *

    c = api.OAuthClient(
        client_id,
        client_secret,
        username,
        password,    
    )
    print c.Item.find(22342)

Notes
------

It is possible to override the default response handler by passing handler as
a keyword argument to a transport function call. For example:

    x = lambda x,y: (x,y)
    result = c.Item.find(11007, basic=True, handler=x)
    ($result, $data) #Returned info

Tests
-----

To run tests for the API wrapper, you need two additional dependencies:

* mock
* nose

With those installed, run `nosetests` from the repository's root directory.


Meta
----

* Code: `git clone git://github.com/podio/podio-py.git`
* Home: <https://github.com/podio/podio-py>
* Bugs: <https://github.com/podio/podio-py/issues>
