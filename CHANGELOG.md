# Changelog

## [2.1.0](https://github.com/stkr22/private-assistant-spotify-skill-py/compare/v2.0.1...v2.1.0) (2026-01-02)


### Features

* :arrow_up: migrate from Redis to Valkey package and update dependencies ([#70](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/70)) ([764e546](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/764e546eeaab89b800d0db359daaae2193fbd00f))
* :recycle: modernize database engine and update tests for commons 5.4.0 ([#70](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/70)) ([1eb59bf](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/1eb59bf1129f739f34a0debcb941e0943480d5c1))
* :sparkles: initialize SpotifySettings and ValkeySettings separately ([#70](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/70)) ([c6aaad5](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/c6aaad57f2319700d08bb535d494a52736706ce9))
* :wrench: improve DevContainer configuration for Podman compatibility ([cc5afdd](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/cc5afdddd5cc03e0e396324ec8388492be582d3f))
* modernize skill infrastructure and configuration (closes [#70](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/70)) ([5c1da9c](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/5c1da9c0ec5bfe4803137e3ff1381e0b0336ac53))


### Bug Fixes

* :bug: fix PostgresConfig type hint in integration tests ([#70](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/70)) ([4e02bee](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/4e02bee3e20890058df984b7eaf8d0b10c9354ca))

## [2.0.1](https://github.com/stkr22/private-assistant-spotify-skill-py/compare/v2.0.0...v2.0.1) (2025-12-18)


### Bug Fixes

* :bug: add REDIS_USERNAME support for Redis ACL authentication ([6f029fc](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/6f029fc34605ecfed5183d8adf7aded96bc5f612))
* :bug: add REDIS_USERNAME support for Redis ACL authentication ([b9491fd](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/b9491fd9d185ce1f35b7c840a8df3c5854043aa0))

## [2.0.0](https://github.com/stkr22/private-assistant-spotify-skill-py/compare/v1.3.0...v2.0.0) (2025-12-18)


### ⚠ BREAKING CHANGES

* Spotify and Redis credentials now use environment variables with SPOTIFY_ and REDIS_ prefixes instead of YAML config.

### Features

* :sparkles: migrate to commons 5.2.0+ with Redis token cache ([1a35a1d](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/1a35a1d5e000e3a7ad2e42efbe3217b175c99f82)), closes [#63](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/63) [#53](https://github.com/stkr22/private-assistant-spotify-skill-py/issues/53)


### Documentation

* add comprehensive documentation and docstrings ([41a7b25](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/41a7b257cb320b9da771a4914a3521ae8ebfb336))
* add comprehensive documentation and docstrings ([767eb40](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/767eb408b5a5aa3888ef8d874926b882a827ba26))

## [1.3.0](https://github.com/stkr22/private-assistant-spotify-skill-py/compare/v1.2.1...v1.3.0) (2025-08-12)


### Features

* :fire: remove pyamaha dependency and functionality [AI] ([ca2f554](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/ca2f554a910eb65a5ec6e026756153268a62a1a8))
* :fire: remove pyamaha dependency and functionality [AI] ([74f01db](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/74f01dbed3ab624122bda5fa22314229d35b1d27))

## [1.2.1](https://github.com/stkr22/private-assistant-spotify-skill-py/compare/v1.2.0...v1.2.1) (2025-08-12)


### Bug Fixes

* implement required skill_preparations abstract method [AI] ([76636d8](https://github.com/stkr22/private-assistant-spotify-skill-py/commit/76636d86b54913cea187803e35a50e4f7bc6061e))
