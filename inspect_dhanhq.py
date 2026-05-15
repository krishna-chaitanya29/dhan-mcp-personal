#!/usr/bin/env python3
"""Inspect the dhanhq SDK API documentation."""

import inspect
import dhanhq

print("=" * 80)
print("DHANHQ SDK API INSPECTION")
print("=" * 80)

# Get version
try:
    import importlib.metadata
    version = importlib.metadata.version("dhanhq")
    print(f"\nInstalled Version: {version}\n")
except:
    print("\nVersion info not available\n")

# Inspect the dhanhq class
client = dhanhq.dhanhq
print(f"Main Class: {client.__name__}")
print(f"Module: {client.__module__}")
print()

# Get all public methods
print("PUBLIC METHODS")
print("-" * 80)
methods = []
for name, method in inspect.getmembers(client, predicate=inspect.ismethod):
    if not name.startswith('_'):
        methods.append((name, method))

for name, method in inspect.getmembers(client, predicate=inspect.isfunction):
    if not name.startswith('_'):
        methods.append((name, method))

# Also try to get from __dict__
for name in dir(client):
    if not name.startswith('_'):
        try:
            attr = getattr(client, name)
            if callable(attr) and (name, attr) not in methods:
                methods.append((name, attr))
        except:
            pass

# Remove duplicates
methods = list(dict.fromkeys(methods))
methods.sort()

for name, method in methods:
    try:
        sig = inspect.signature(method)
        doc = inspect.getdoc(method)
        print(f"\n► {name}{sig}")
        if doc:
            doc_lines = doc.split('\n')
            for line in doc_lines[:5]:  # First 5 lines of docstring
                print(f"  {line}")
            if len(doc_lines) > 5:
                print(f"  ... ({len(doc_lines) - 5} more lines)")
    except Exception as e:
        print(f"\n► {name}")
        print(f"  Error getting signature: {e}")

print("\n" + "=" * 80)
