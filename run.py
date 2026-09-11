#!/usr/bin/env python3
"""Start the web service. Historical CLI source is preserved in legacy/run.py."""
import argparse
from rddns_web.app import main

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RDDNS web service; configure routers and DNS in the browser.')
    parser.parse_args()
    main()
