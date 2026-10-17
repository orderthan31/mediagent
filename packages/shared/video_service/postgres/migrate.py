"""Explicit migration command. DSN is read from the named environment variable."""
import argparse
import os
from . import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dsn-env', required=True, help='Environment variable containing the target PostgreSQL DSN')
    args = parser.parse_args()
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        parser.error('The named DSN environment variable is empty')
    applied = Database(dsn).migrate()
    print('Applied: ' + (', '.join(applied) or 'none (already current)'))


if __name__ == '__main__':
    main()
