"""
Playwright-driven simulated user.

Drives the actual browser UI: registers + logs in via the login form,
navigates to ``/annotate``, applies annotations through real DOM events
(clicking radios, filling textareas, ticking checkboxes), then clicks
the Next button to advance.

Designed as a slow-but-real smoke test of the rendered annotation UI:
the same code paths a human user would hit. The annotation values still
come from an :class:`AnnotationStrategy` (typically
:class:`AgentSimulatorStrategy`); Playwright is only the *driver*.

Constraints:
  - Single user, sequential. Browser sessions don't parallelize cleanly.
  - Requires ``playwright`` + a chromium install
    (``pip install playwright && playwright install chromium``).
  - Falls back gracefully if Playwright is unavailable: raises a clear
    ``ImportError`` at construction time.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from .annotation_strategies import AnnotationStrategy, create_strategy
from .competence_profiles import create_competence_profile
from .config import (
    AnnotationStrategyType,
    InteractiveConfig,
    UserConfig,
)
from .interactive_runner import InteractiveSessionRunner
from .timing_models import NoWaitTimingModel, TimingModel
from .user_simulator import AnnotationRecord, UserSimulationResult

logger = logging.getLogger(__name__)


@dataclass
class _DomSubmissionResult:
    """How many DOM inputs we successfully applied vs total annotations."""

    applied: int
    total: int


class PlaywrightSimulatedUser:
    """Browser-driven simulated user.

    Public surface mirrors :class:`SimulatedUser` enough that a smoke runner
    can use either. ``run_simulation()`` returns a
    :class:`UserSimulationResult` so existing reporting works.
    """

    def __init__(
        self,
        user_config: UserConfig,
        server_url: str,
        gold_standards: Optional[Dict[str, Dict[str, Any]]] = None,
        simulate_wait: bool = False,
        interactive_config: Optional[InteractiveConfig] = None,
        headless: bool = True,
        debounce_seconds: float = 1.8,
    ):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "PlaywrightSimulatedUser requires playwright. Install it with:\n"
                "    pip install playwright\n"
                "    playwright install chromium"
            ) from e

        self.config = user_config
        self.server_url = server_url.rstrip("/")
        self.gold_standards = gold_standards or {}
        self.headless = headless
        self.debounce_seconds = debounce_seconds

        self.competence = create_competence_profile(user_config.competence)
        self.strategy = self._create_strategy()

        self.timing = (
            TimingModel(user_config.timing)
            if simulate_wait
            else NoWaitTimingModel(user_config.timing)
        )

        # API session is mirrored to/from Playwright for /api/* fetches
        self.api_session = requests.Session()

        self.interactive_runner: Optional[InteractiveSessionRunner] = None
        if interactive_config and interactive_config.enabled:
            self.interactive_runner = InteractiveSessionRunner(
                interactive_config, server_url
            )

        self.result = UserSimulationResult(user_id=user_config.user_id)
        self.schemas: List[Dict[str, Any]] = []

        # Lazily set in start()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # Strategy & lifecycle
    # ------------------------------------------------------------------

    def _create_strategy(self) -> AnnotationStrategy:
        return create_strategy(
            strategy_type=self.config.strategy,
            llm_config=self.config.llm_config,
            biased_config=self.config.biased_config,
            pattern_config=self.config.pattern_config,
            agent_config=self.config.agent_config,
            user_id=self.config.user_id,
        )

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def stop(self) -> None:
        for closer in (self._page, self._context, self._browser):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._page = self._context = self._browser = self._pw = None

    # ------------------------------------------------------------------
    # Cookie sharing
    # ------------------------------------------------------------------

    def _sync_cookies_to_api(self) -> None:
        """Copy Playwright cookies into the requests session."""
        if self._context is None:
            return
        for cookie in self._context.cookies():
            self.api_session.cookies.set(
                cookie["name"], cookie["value"], domain=cookie.get("domain")
            )

    # ------------------------------------------------------------------
    # Login via UI
    # ------------------------------------------------------------------

    def login_via_ui(self) -> bool:
        """Register + log in. Uses the API for the credential exchange (the
        UI form mode is brittle across templates), then loads the cookies
        into Playwright so DOM interactions work in a logged-in session."""
        password = "simulated_password_123"
        try:
            self.api_session.post(
                f"{self.server_url}/register",
                data={"action": "signup", "email": self.config.user_id, "pass": password},
                allow_redirects=True,
                timeout=30,
            )
            self.api_session.post(
                f"{self.server_url}/auth",
                data={"action": "login", "email": self.config.user_id, "pass": password},
                allow_redirects=True,
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            logger.warning("API login failed: %s", e)
            return False

        # Push cookies into Playwright so the page renders as logged-in.
        self._sync_cookies_to_browser()

        # Navigate to /annotate; walk past consent/instructions if needed.
        page = self._page
        try:
            page.goto(f"{self.server_url}/annotate", wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            logger.warning("page.goto /annotate failed: %s", e)

        for _ in range(10):
            self._sync_cookies_to_api()
            if self._is_in_annotation_phase():
                # Make sure the annotation page is what's rendered
                try:
                    page.wait_for_selector("#next-btn", timeout=5000)
                except Exception:
                    pass
                return True
            # Try a UI advance (consent / instructions screen)
            self._advance_phase_screen()
            time.sleep(0.5)
            try:
                page.goto(f"{self.server_url}/annotate", wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass

        return self._is_in_annotation_phase()

    def _sync_cookies_to_browser(self) -> None:
        """Push cookies from the API session into the Playwright context."""
        if self._context is None:
            return
        cookies = []
        for c in self.api_session.cookies:
            cookies.append({
                "name": c.name,
                "value": c.value,
                "url": self.server_url,
            })
        if cookies:
            try:
                self._context.add_cookies(cookies)
            except Exception as e:
                logger.warning("add_cookies failed: %s", e)

    def _is_in_annotation_phase(self) -> bool:
        """We're in annotation phase iff /api/current_instance returns 200."""
        try:
            r = self.api_session.get(
                f"{self.server_url}/api/current_instance", timeout=10
            )
        except requests.exceptions.RequestException:
            return False
        return r.status_code == 200

    def _advance_phase_screen(self) -> None:
        """Click any visible 'Next' / 'Continue' / 'I agree' button."""
        page = self._page
        candidates = [
            "#next-btn:visible",
            "button:has-text('Continue')",
            "button:has-text('I Agree')",
            "button:has-text('Start')",
            "input[type='submit']:visible",
        ]
        for sel in candidates:
            loc = page.locator(sel)
            if loc.count() > 0:
                try:
                    loc.first.click()
                    return
                except Exception:
                    continue

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def fetch_schemas(self) -> List[Dict[str, Any]]:
        try:
            r = self.api_session.get(f"{self.server_url}/api/schemas", timeout=30)
            if r.status_code != 200:
                return []
            data = r.json()
            if isinstance(data, dict):
                schemas = (
                    list(data["schemas"].values())
                    if isinstance(data.get("schemas"), dict)
                    else data.get("schemas", list(data.values()))
                )
            else:
                schemas = data
            self.schemas = schemas
            return schemas
        except requests.exceptions.RequestException as e:
            logger.warning("schema fetch failed: %s", e)
            return []

    def fetch_current_instance(self) -> Optional[Dict[str, Any]]:
        try:
            r = self.api_session.get(
                f"{self.server_url}/api/current_instance", timeout=30
            )
        except requests.exceptions.RequestException:
            return None
        if r.status_code != 200:
            return None
        return r.json()

    # ------------------------------------------------------------------
    # DOM annotation application
    # ------------------------------------------------------------------

    def _apply_annotations(self, annotations: Dict[str, Any]) -> _DomSubmissionResult:
        """Translate a wire-format annotation dict into DOM clicks/fills."""
        page = self._page
        applied = 0
        total = 0
        for key, value in annotations.items():
            total += 1
            if ":" not in key:
                continue
            schema, label = key.split(":", 1)
            if label == "text":
                # textarea / textbox
                # name: <schema>:::text via generate_element_identifier
                sel = f"[name=\"{schema}:::text\"]"
                if page.locator(sel).count() == 0:
                    sel = f"textarea[name*='{schema}']"
                if page.locator(sel).count() > 0:
                    try:
                        page.locator(sel).first.fill(str(value)[:1000])
                        applied += 1
                    except Exception as e:
                        logger.debug("fill failed for %s: %s", sel, e)
                continue

            # Try radio (name=schema, value=label)
            radio_sel = f"input[type='radio'][name=\"{schema}\"][value=\"{label}\"]"
            if page.locator(radio_sel).count() > 0:
                try:
                    page.locator(radio_sel).first.check(force=True)
                    applied += 1
                    continue
                except Exception:
                    pass

            # Try checkbox / multiselect (name=<schema>:::<label>)
            cb_sel = f"input[type='checkbox'][name=\"{schema}:::{label}\"]"
            if page.locator(cb_sel).count() > 0:
                try:
                    page.locator(cb_sel).first.check(force=True)
                    applied += 1
                    continue
                except Exception:
                    pass

            # Likert (rendered as radios with name=<schema>:::<label> in some templates)
            alt_radio = f"input[type='radio'][name=\"{schema}:::{label}\"]"
            if page.locator(alt_radio).count() > 0:
                try:
                    page.locator(alt_radio).first.check(force=True)
                    applied += 1
                    continue
                except Exception:
                    pass

            logger.debug("no DOM target for %s=%s", key, value)

        return _DomSubmissionResult(applied=applied, total=total)

    def _click_next(self) -> bool:
        page = self._page
        next_btn = page.locator("#next-btn")
        if next_btn.count() == 0:
            return False
        try:
            next_btn.first.click()
            return True
        except Exception as e:
            logger.warning("next-btn click failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_simulation(
        self, max_annotations: Optional[int] = None
    ) -> UserSimulationResult:
        self.result.start_time = datetime.now()
        max_ann = (
            max_annotations
            if max_annotations is not None
            else self.config.max_annotations
        )

        try:
            self.start()
            if not self.login_via_ui():
                self.result.errors.append("login_via_ui failed")
                return self.result

            self.fetch_schemas()
            if not self.schemas:
                self.result.errors.append("no schemas returned by /api/schemas")

            count = 0
            seen_instances = set()
            while True:
                if max_ann is not None and count >= max_ann:
                    break

                instance = self.fetch_current_instance()
                if not instance or not instance.get("instance_id"):
                    break
                instance_id = instance["instance_id"]
                if instance_id in seen_instances:
                    # Server didn't advance after Next click; stop to avoid
                    # an infinite loop.
                    break
                seen_instances.add(instance_id)

                # Optional interactive chat first
                if self.interactive_runner is not None:
                    data = instance.get("data") or {}
                    task_text = (
                        data.get("task_description")
                        or data.get("text")
                        or instance.get("text", "")
                    )
                    chat_result = self.interactive_runner.run(
                        self.api_session, instance_id, task_text
                    )
                    if chat_result.error:
                        self.result.errors.append(
                            f"interactive: {chat_result.error}"
                        )
                    refreshed = self.fetch_current_instance()
                    if refreshed and refreshed.get("instance_id") == instance_id:
                        instance = refreshed

                response_time = self.timing.get_response_time(0.0)
                self.timing.wait(response_time)

                # Generate annotations using the strategy
                instance_for_strategy = dict(instance)
                instance_for_strategy["__all_schemas__"] = self.schemas

                gold_answer = self.gold_standards.get(instance_id)

                all_annotations: Dict[str, Any] = {}
                for schema in self.schemas:
                    schema_name = schema.get("name")
                    schema_gold = (
                        {schema_name: gold_answer.get(schema_name)}
                        if gold_answer
                        else None
                    )
                    ann = self.strategy.generate_annotation(
                        instance_for_strategy,
                        schema,
                        self.competence,
                        schema_gold,
                    )
                    all_annotations.update(ann)

                # Apply via DOM
                dom_result = self._apply_annotations(all_annotations)

                # Wait for the debounced auto-save to fire
                time.sleep(self.debounce_seconds)

                # Reload Playwright cookies into the API session in case the
                # server set new ones during the save.
                self._sync_cookies_to_api()

                self.result.annotations.append(
                    AnnotationRecord(
                        instance_id=instance_id,
                        schema_name=",".join(all_annotations.keys()),
                        annotation=all_annotations,
                        response_time=response_time,
                        timestamp=datetime.now(),
                    )
                )
                count += 1
                logger.info(
                    "[playwright] %s annotated %s (DOM %d/%d)",
                    self.config.user_id,
                    instance_id,
                    dom_result.applied,
                    dom_result.total,
                )

                if not self._click_next():
                    break
                # Wait for the next instance to render
                self._page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(0.3)

        except Exception as e:
            logger.error("Playwright simulation error: %s", e, exc_info=True)
            self.result.errors.append(f"playwright: {e}")
        finally:
            self.result.end_time = datetime.now()
            self.result.total_time = (
                self.result.end_time - self.result.start_time
            ).total_seconds()
            self.stop()

        return self.result
