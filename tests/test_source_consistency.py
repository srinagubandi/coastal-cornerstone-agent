
import unittest
from agent import valid_source


class SourceHttpsOnlyRegressionTest(unittest.TestCase):
    def test_https_allowed_http_rejected_for_real_allowed_host(self):
        self.assertTrue(valid_source("https://cccbuild.com/approved-source-path/"))
        self.assertFalse(valid_source("http://cccbuild.com/approved-source-path/"))
