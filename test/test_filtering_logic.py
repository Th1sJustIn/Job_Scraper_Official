import re
import unittest

class TestFilteringLogic(unittest.TestCase):
    def setUp(self):
        self.FILTER_KEYWORDS = [
            r'\bsenior\b', r'\bmanager\b', r'\bdirector\b', r'\blead\b', 
            r'\bprincipal\b', r'\bstaff\b', r'\bhead of\b', r'\bvp\b', 
            r'\bvice president\b', r'\bchief\b'
        ]
        self.regex = re.compile('|'.join(self.FILTER_KEYWORDS), re.IGNORECASE)

    def test_filter_keywords(self):
        cases = [
            ("Senior Software Engineer", True),
            ("Software Engineering Manager", True),
            ("Director of Engineering", True),
            ("Lead Developer", True),
            ("Principal Researcher", True),
            ("Staff Engineer", True),
            ("Head of Product", True),
            ("VP of Sales", True),
            ("Vice President Operations", True),
            ("Chief Technology Officer", True),
            ("Software Engineer", False),
            ("Junior Data Scientist", False),
            ("Product Designer", False),
            ("Engineering Lead (L5)", True), # Should match 'lead'
            ("Senior Data Scientist (Mid-Level)", True), # Should match 'senior'
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(bool(self.regex.search(title)), expected)

if __name__ == '__main__':
    unittest.main()
