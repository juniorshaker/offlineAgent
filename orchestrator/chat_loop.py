"""
orchestrator/chat_loop.py
Main conversation loop with all guards, hooks, and tool dispatch.
"""

import sys
import threading
from pathlib import Path

from .state_manager import StateManager
from .context_compressor import compress_history
from .error_recovery import check_before_send, repair_after_error
from .topic_guard import detect_topic_shift, ask_user_new_conversation


def _estimate_tokens(text: str) -> int:
    """Quick token estimation."""
    from .state_manager import TokenEstimator
    return TokenEstimator.estimate(text)


def _llm_call_with_timeout(llm_fn, messages, timeout_sec: int) -> str:
    """Call LLM with a timeout. Returns error string on timeout."""
    result_container = {"response": None, "error": None, "done": False}

    def _call():
        try:
            result_container["response"] = llm_fn(messages)
        except Exception as e:
            result_container["error"] = str(e)
        finally:
            result_container["done"] = True

    thread = threading.Thread(target=_call, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)

    if not result_container["done"]:
        return f"[Timeout] LLM did not respond within {timeout_sec}s."

    if result_container["error"]:
        return f"[Error] {result_container['error']}"

    return result_container["response"] or ""


class ChatLoop:
    """Orchestrates the full conversation loop."""

    def __init__(
        self,
        config: dict,
        base_dir: Path,
        system_prompt: str,
        skills: list,
        state: StateManager,
        tools_registry,
        llm_chat_fn,
        memory_store=None,
        logger=None,
        switch_backend_fn=None,
        get_active_model_fn=None,
        list_backends_fn=None,
    ):
        self.config = config
        self.base_dir = base_dir
        self.system_prompt = system_prompt
        self.skills = skills
        self.state = state
        self.tools = tools_registry
        self.llm_chat_fn = llm_chat_fn
        self.switch_backend_fn = switch_backend_fn
        self.get_active_model_fn = get_active_model_fn
        self.list_backends_fn = list_backends_fn
        self.memory_store = memory_store
        self.logger = logger
        self.running = True
        self._topic_guard_disabled = False
        self._turn_since_check = 0

    def run(self):
        """Start the interactive chat loop."""
        print("\n  OfflineAgent -- Type /help for commands, /exit to quit.\n")
        print(f"  Skills loaded: {len(self.skills)}")
        print(f"  Tools: {', '.join(self.tools.names())}")
        print()

        while self.running:
            try:
                user_input = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n")
                self._handle_exit()
                break

            if not user_input:
                continue

            # Built-in commands
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            # Normal conversation turn
            self._handle_turn(user_input)

    # ── Command handlers ──

    def _handle_command(self, cmd: str):
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command == "/exit":
            self._handle_exit()
            self.running = False

        elif command == "/model":
            if not self.switch_backend_fn:
                print("  Backend switching not available.")
            elif not arg:
                if self.list_backends_fn:
                    print("\n  LLM Backends:")
                    print(self.list_backends_fn())
                    print("\n  Usage: /model <name>  to switch active backend")
                else:
                    print("  No backend info available.")
            else:
                result = self.switch_backend_fn(arg)
                print(f"  {result}")

        elif command == "/help":
            print("""
  Built-in commands:
    /help          Show this help
    /model         Switch LLM backend (e.g. /model primary)
    /skills        List loaded skills
    /skill <name>  Load a skill's full instructions
    /tools         List available tools
    /status        Token budget dashboard
    /memory        Show memory list
    /memory <id>   Show a specific memory
    /clear         Clear conversation history
    /config        Show current config summary
    /exit          Exit (auto-summarize + feedback)
""")

        elif command == "/skills":
            if not self.skills:
                print("  No skills loaded.")
            else:
                for s in self.skills:
                    use_hint = f" [used {s.use_count}x]" if s.use_count > 0 else ""
                    print(f"  [{s.source}] {s.name}{use_hint}: {s.short_desc}")

        elif command == "/skill":
            if not arg:
                print("  Usage: /skill <name>")
            else:
                from ..prompt_layer.skill_loader import get_skill_body
                found = None
                for s in self.skills:
                    if s.name.lower() == arg.lower():
                        found = s
                        break
                if found:
                    body = get_skill_body(found)
                    found.use_count += 1
                    self.state.add_user_message(f"/skill {found.name}")
                    self.state.add_assistant_message(f"## Skill: {found.name}\n\n{body}")
                    print(f"\n  Loaded skill: {found.name}\n")
                    print(body[:500] + ("..." if len(body) > 500 else ""))
                    print()
                else:
                    print(f"  Skill not found: {arg}")

        elif command == "/tools":
            print(f"  Available tools: {', '.join(self.tools.names())}")

        elif command == "/status":
            status = self.state.status_summary(self.system_prompt)
            print(f"""
  Session Status
    Estimated tokens:  {status['tokens_estimate']} / {status['max_tokens']} ({status['usage_percent']}%)
    Conversation turns: {status['turns']} / {status['max_history']}
    Skills loaded:      {len(self.skills)}
""")

        elif command == "/memory":
            if not self.memory_store:
                print("  Memory system not available.")
            elif not arg:
                memories = self.memory_store.list_all()
                if not memories:
                    print("  No memories yet.")
                else:
                    for m in memories[:10]:
                        print(f"  [{m['id']}] {m['summary'][:80]}")
            else:
                mem = self.memory_store.get(arg)
                if mem:
                    print(f"\n{mem}\n")
                else:
                    print(f"  Memory not found: {arg}")

        elif command == "/clear":
            self.state.clear_history()
            print("  Conversation history cleared.")

        elif command == "/config":
            print()
            print("  Config Summary")
            # Show backends
            if self.list_backends_fn:
                backend_list = self.list_backends_fn()
                print("  LLM Backends:")
                print(backend_list)
            else:
                llm = self.config.get("llm", {})
                print(f"  LLM URL:   {llm.get('url', 'N/A')}")
                print(f"  Model:     {llm.get('model', 'N/A')}")
            print(f"  Max history: {self.config.get('agent', {}).get('max_history', 'N/A')}")
            print(f"  Max tokens:  {self.config.get('agent', {}).get('max_tokens_estimate', 'N/A')}")
            print()

        else:
            print(f"  Unknown command: {command}. Type /help for list.")

    # ── Turn handler ──


    # ── Auto skill injector ──

    def _auto_inject_skill(self, user_input: str):
        """Phase 1: keyword pre-filter → Phase 2: LLM decides if multiple candidates.
        
        Keywords come from config.yaml skill_keywords and per-skill triggers.
        When only 1 candidate matches, inject directly (no LLM call).
        When 2+ candidates match, use LLM to pick the best one.
        """
        si_cfg = self.config.get("agent", {}).get("skill_injection", {})
        if not si_cfg.get("enabled", True):
            return

        lower = user_input.lower()

        # Phase 1: keyword pre-filter from config + per-skill triggers
        keyword_map = self.config.get("skill_keywords", {})
        candidates = []
        for skill_name, keywords in keyword_map.items():
            if not isinstance(keywords, list):
                continue
            for kw in keywords:
                if kw in lower:
                    candidates.append(skill_name)
                    break  # one keyword match is enough per skill

        # Also check triggers from skill frontmatter (per-skill customization)
        for s in self.skills:
            if s.name.lower() in [c.lower() for c in candidates]:
                continue
            # triggers from frontmatter: comma-separated string
            triggers_raw = s.frontmatter.get("triggers", "") if hasattr(s, "frontmatter") else ""
            if triggers_raw:
                triggers = [t.strip() for t in triggers_raw.split(",") if t.strip()]
                for t in triggers:
                    if t.lower() in lower:
                        candidates.append(s.name)
                        break

        if not candidates:
            return

        # Deduplicate while preserving priority order
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c.lower() not in seen:
                seen.add(c.lower())
                unique_candidates.append(c)
        candidates = unique_candidates

        # Phase 2: select
        selected = None
        if len(candidates) == 1:
            selected = candidates[0]
        elif si_cfg.get("llm_selection", True):
            selected = self._llm_pick_skill(user_input, candidates, si_cfg)

        if not selected:
            return

        # Find the skill object
        found = None
        for s in self.skills:
            if s.name.lower() == selected.lower():
                found = s
                break
        if not found:
            if self.logger:
                self.logger.error_recovery(
                    "skill_inject", f"skill not found: {selected}", "skip"
                )
            return

        # Don't re-inject if already in recent messages
        recent = [m.get("content", "") for m in self.state.messages[-5:]]
        if any(f"[Skill Context: {found.name}]" in c for c in recent):
            return

        # Inject L2 body
        from ..prompt_layer.skill_loader import get_skill_body

        body = get_skill_body(found)
        found.use_count += 1
        injected = f"[Skill Context: {found.name}]\n\n{body}"
        self.state.add_assistant_message(injected)
        if self.logger:
            self.logger.skill_injected(found.name, len(body))

    def _llm_pick_skill(self, user_input: str, candidates: list, si_cfg: dict) -> str | None:
        """Ask LLM to pick the best matching skill from candidates."""
        candidate_descs = []
        for cn in candidates:
            for s in self.skills:
                if s.name.lower() == cn.lower():
                    desc = getattr(s, "short_desc", "") or getattr(s, "description", "") or cn
                    line = f"- {s.name}: {desc}"
                    # Include applicable/not_applicable hints if present
                    if hasattr(s, "frontmatter") and s.frontmatter:
                        app = s.frontmatter.get("applicable", "")
                        not_app = s.frontmatter.get("not_applicable", "")
                        if app:
                            line += f"\n  Use for: {app}"
                        if not_app:
                            line += f"\n  NOT for: {not_app}"
                    candidate_descs.append(line)
                    break

        prompt = (
            f"User request: \"{user_input}\"\n\n"
            "Available skills:\n"
            + "\n".join(candidate_descs)
            + "\n\nWhich ONE skill BEST matches the user's request? "
            "Reply with ONLY the skill name (or \"none\" if none fit).\n"
            "Skill name:"
        )

        timeout = si_cfg.get("llm_selection_timeout", 15)
        messages = [{"role": "user", "content": prompt}]

        try:
            result = _llm_call_with_timeout(self.llm_chat_fn, messages, timeout)
        except Exception:
            if self.logger:
                self.logger.error_recovery("skill_pick", "LLM call failed", "fallback_first")
            return candidates[0]  # fallback to first candidate

        if not result or result.startswith("[Timeout]") or result.startswith("[Error]"):
            if self.logger:
                self.logger.error_recovery("skill_pick", result[:80] if result else "empty", "fallback_first")
            return candidates[0]  # fallback to first candidate

        result = result.strip().strip('"').strip("'").strip()

        # Try exact match first, then prefix match
        for cn in candidates:
            if cn.lower() == result.lower():
                return cn
        for cn in candidates:
            if result.lower().startswith(cn.lower()[:8]):
                return cn
        if result.lower() == "none" or result == "":
            return None

        # Last resort: fallback to first candidate
        return candidates[0]

    def _handle_turn(self, user_input: str):
        """Process one conversation turn."""
        if self.logger:
            self.logger.turn_start(user_input)

        agent_cfg = self.config.get("agent", {})
        llm_timeout = self.config.get("llm", {}).get("timeout", 60)

        # ── Topic guard ──
        if (
            agent_cfg.get("topic_guard", {}).get("enabled", True)
            and not self._topic_guard_disabled
        ):
            self._turn_since_check += 1
            check_interval = agent_cfg.get("topic_guard", {}).get("check_interval", 1)
            if self._turn_since_check >= check_interval:
                self._turn_since_check = 0
                # Wrap topic guard LLM call with timeout
                result_raw = _llm_call_with_timeout(
                    lambda msgs: detect_topic_shift(self.state, user_input, self.llm_chat_fn),
                    [{"role": "user", "content": "ping"}],
                    timeout_sec=min(llm_timeout, 30),
                )
                if result_raw.startswith("[Timeout]") or result_raw.startswith("[Error]"):
                    if self.logger:
                        self.logger.error_recovery("topic_guard", result_raw[:100], "skip")
                    result = "SAME"
                else:
                    result = result_raw

                if result == "DIFFERENT":
                    recent_msgs = self.state.get_recent_assistant_messages(count=2)
                    from_topic = recent_msgs[0][:60] if recent_msgs else "unknown"
                    choice = ask_user_new_conversation(from_topic, user_input[:60])
                    if choice == "Y":
                        self.state.clear_history()
                        if self.logger:
                            self.logger.topic_shift(from_topic, user_input[:60], "Y")
                    elif choice == "S":
                        self._topic_guard_disabled = True
                        if self.logger:
                            self.logger.topic_shift(from_topic, user_input[:60], "S")
                    else:
                        if self.logger:
                            self.logger.topic_shift(from_topic, user_input[:60], "N")

        # ── Add user message to state ──
        self.state.add_user_message(user_input)

        # ── Auto-inject relevant skill L2 ──
        self._auto_inject_skill(user_input)

        # ── Error recovery: pre-check ──
        model = self.get_active_model_fn() if self.get_active_model_fn else self.config.get("llm", {}).get("model", "")
        messages_for_api = self.state.get_history_for_api(self.system_prompt)
        stripped = check_before_send(model, messages_for_api[1:], self.base_dir / "memory")
        if stripped:
            non_system = [m for m in self.state.messages if m["role"] != "system"]
            self.state.messages = [m for m in self.state.messages if m["role"] == "system"] + stripped

        # ── Compression check ──
        compression_cfg = agent_cfg.get("compression", {})
        if compression_cfg.get("enabled", True):
            trigger = compression_cfg.get("trigger_ratio", 0.7)
            if self.state.needs_compression(trigger):
                before_tokens = self.state.estimate_total_tokens()
                try:
                    success = compress_history(
                        self.state,
                        self.system_prompt,
                        self.llm_chat_fn,
                        keep_recent=compression_cfg.get("keep_recent", 2),
                    )
                except Exception as e:
                    if self.logger:
                        self.logger.error_recovery("compress", str(e)[:100], "skip")
                    success = False
                if success and self.logger:
                    after_tokens = self.state.estimate_total_tokens()
                    self.logger.compression(before_tokens, after_tokens)

        # ── Tool execution loop ──
        from ..tool_layer.tool_executor import execute_tool_loop

        response = execute_tool_loop(
            self.llm_chat_fn,
            self.system_prompt,
            self.state,
            self.config,
            self.tools,
            self.logger,
        )

        # ── Add assistant response to state ──
        self.state.add_assistant_message(response)

        # ── Display ──
        print(f"\nAgent> {response}\n")

    # ── Exit handler ──

    def _handle_exit(self):
        memory_cfg = self.config.get("agent", {}).get("memory", {})

        # Close browser if open
        try:
            from ..tool_layer.browser_tools import browser_close
            browser_close()
            print("  Browser session closed.")
        except Exception:
            pass

        # Auto-summarize
        if memory_cfg.get("auto_summarize_on_exit", True) and self.memory_store:
            non_system_msgs = [m for m in self.state.messages if m["role"] != "system"]
            if len(non_system_msgs) >= 4:
                from ..memory_layer.memory_summarizer import summarize_conversation
                print("\n  Generating session summary...")
                summary = summarize_conversation(non_system_msgs, self.llm_chat_fn)
                if summary:
                    mem_id = self.memory_store.add(summary)
                    print(f"  Memory saved: {mem_id}")

        # Skill draft check
        non_system_msgs = [m for m in self.state.messages if m["role"] != "system"]
        topic = None
        try:
            from ..memory_layer.skill_drafter import detect_skill_worthy_topic
            topic = detect_skill_worthy_topic(non_system_msgs)
        except Exception:
            pass

        if topic:
            print(f"\n  [Tip] This conversation covered '{topic}'. Generate a SKILL.md draft? [Y/n]: ", end="")
            try:
                choice = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "n"
            if choice in ("", "y", "yes"):
                from ..memory_layer.skill_drafter import generate_skill_draft, save_skill_draft
                draft = generate_skill_draft(topic, self.llm_chat_fn)
                if draft:
                    slug = topic.lower().replace(" ", "-")
                    saved = save_skill_draft(self.base_dir / "skills", slug, draft)
                    if saved:
                        print(f"  Skill draft saved: {saved}")

        # Feedback
        feedback_cfg = self.config.get("agent", {}).get("feedback", {})
        if feedback_cfg.get("enabled", True):
            from ..metrics.feedback import collect_feedback, save_feedback
            fb = collect_feedback(self.base_dir)
            if fb:
                save_feedback(self.base_dir, fb)

        # Write log
        if self.logger:
            self.logger.write_log_file()

        print("\n  Goodbye!\n")
