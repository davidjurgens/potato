# Changelog

All notable changes to the Potato annotation platform are documented in this file.

## [this repo] - My version

- Changed the instance display logic:
	- Instances are now not inserted at the top of all the pages by default;
	- You can now insert part of the instance (e.g. `{{ display_fields["user_query"] }}`) 
- Added an 'Instructions' button to navbar during annotation which opens a task instructions pop-up, when instructions page is passed.

## [2.2.0] - Comprehensive Annotation & Export Platform

9 new annotation schemas, MACE annotator competence estimation, diversity ordering, pluggable export system with 8 formats, extended remote data sources, standard survey instruments, and annotation navigation.

**[Full Release Notes →](docs/releasenotes/v2.2.0.md)**

---

## [2.1.0] - Adjudication & Multi-Modal Annotation

Complete adjudication workflow, flexible instance display system, multi-field span annotation, span linking, and visual AI support.

**[Full Release Notes →](docs/releasenotes/v2.1.0.md)**

---

## [2.0.0] - Backend Refactor

Major architectural overhaul with new state management, AI support, active learning, training phase, database backend, enhanced admin dashboard, and security enhancements.

**[Full Release Notes →](docs/releasenotes/v2.0.0.md)**

---

## Migration

See [MIGRATION.md](MIGRATION.md) for detailed instructions on upgrading from v1.x to v2.0.0.

## New Features Guide

See [docs/new_features_v2.md](docs/new_features_v2.md) for detailed documentation on new features.
