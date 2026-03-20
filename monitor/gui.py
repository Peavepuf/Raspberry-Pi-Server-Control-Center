from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from monitor.i18n import tr


class MonitorDashboard:
    def __init__(self, app) -> None:
        self.app = app
        self.root = tk.Tk()
        self.root.geometry("1450x860")
        self.root.minsize(1180, 720)
        self.refresh_ms = max(1000, int(self.app.config.gui_refresh_seconds * 1000))
        self._refresh_after_id: str | None = None
        self._selected_server_id: int | None = None

        self.status_var = tk.StringVar(value=self._t("starting"))
        self.fan_var = tk.StringVar(value=self._t("fan_status_loading"))
        self.next_jobs_var = tk.StringVar(value=self._t("jobs_loading"))
        self.settings_status_var = tk.StringVar(value=self._t("settings_ready"))

        self.server_name_var = tk.StringVar()
        self.server_address_var = tk.StringVar()
        self.server_enabled_var = tk.BooleanVar(value=True)

        self.fan_pin_var = tk.StringVar()
        self.fan_min_temp_var = tk.StringVar()
        self.fan_max_temp_var = tk.StringVar()
        self.fan_poll_interval_var = tk.StringVar()
        self.telegram_token_var = tk.StringVar()
        self.telegram_chat_ids_var = tk.StringVar()
        self.language_var = tk.StringVar()
        self._language_labels = {"en": self._t("english"), "tr": self._t("turkish")}
        self._language_codes_by_label = {value: key for key, value in self._language_labels.items()}

        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> int:
        self.app.start_scheduler_thread()
        self._refresh_ui()
        self.root.mainloop()
        return 0

    def _build_layout(self) -> None:
        self.root.title(self._t("app_title"))

        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text=self._t("app_title"), font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(header, textvariable=self.status_var).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(header, textvariable=self.fan_var, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(header, textvariable=self.next_jobs_var).pack(anchor=tk.W, pady=(2, 0))

        top_buttons = ttk.Frame(container)
        top_buttons.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(top_buttons, text=self._t("run_check_now"), command=self._run_now).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_buttons, text=self._t("send_daily_summary"), command=self._run_daily).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_buttons, text=self._t("send_weekly_summary"), command=self._run_weekly).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_buttons, text=self._t("refresh"), command=self._refresh_ui).pack(side=tk.LEFT)

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.dashboard_tab = ttk.Frame(notebook, padding=10)
        self.settings_tab = ttk.Frame(notebook, padding=0)
        notebook.add(self.dashboard_tab, text=self._t("dashboard_tab"))
        notebook.add(self.settings_tab, text=self._t("settings_tab"))

        self._build_dashboard_tab()
        self._build_settings_tab()

    def _build_dashboard_tab(self) -> None:
        summary_frame = ttk.LabelFrame(self.dashboard_tab, text=self._t("overview"), padding=10)
        summary_frame.pack(fill=tk.X, pady=(0, 12))
        self.summary_text = tk.Text(summary_frame, height=8, wrap="word")
        self.summary_text.pack(fill=tk.X)
        self.summary_text.configure(state=tk.DISABLED)

        table_frame = ttk.LabelFrame(self.dashboard_tab, text=self._t("tracked_targets"), padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("status", "name", "address", "latency", "http", "ssl", "uptime24", "uptime7", "uptimeall", "last")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "status": self._t("status"),
            "name": self._t("name"),
            "address": self._t("address"),
            "latency": self._t("latency"),
            "http": self._t("http_https"),
            "ssl": self._t("ssl"),
            "uptime24": self._t("uptime_24h"),
            "uptime7": self._t("uptime_7d"),
            "uptimeall": self._t("overall_uptime"),
            "last": self._t("last_check"),
        }
        widths = {
            "status": 120,
            "name": 190,
            "address": 250,
            "latency": 90,
            "http": 150,
            "ssl": 140,
            "uptime24": 120,
            "uptime7": 120,
            "uptimeall": 130,
            "last": 180,
        }
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(key, width=widths[key], anchor=tk.W)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure("up", background="#d9fdd3")
        self.tree.tag_configure("down", background="#ffd6d6")
        self.tree.tag_configure("unknown", background="#ececec")

        details_frame = ttk.LabelFrame(self.dashboard_tab, text=self._t("errors_details"), padding=10)
        details_frame.pack(fill=tk.BOTH, expand=False, pady=(12, 0))
        self.error_text = tk.Text(details_frame, height=8, wrap="word")
        self.error_text.pack(fill=tk.BOTH, expand=True)
        self.error_text.configure(state=tk.DISABLED)

    def _build_settings_tab(self) -> None:
        canvas = tk.Canvas(self.settings_tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.settings_content = ttk.Frame(canvas, padding=10)
        self._settings_window = canvas.create_window((0, 0), window=self.settings_content, anchor="nw")
        self.settings_canvas = canvas

        self.settings_content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(self._settings_window, width=event.width),
        )
        canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)

        ttk.Label(
            self.settings_content,
            textvariable=self.settings_status_var,
            foreground="#004085",
        ).pack(anchor=tk.W, pady=(0, 10))

        language_frame = ttk.LabelFrame(self.settings_content, text=self._t("language_settings"), padding=10)
        language_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(language_frame, text=self._t("language_mode")).grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.language_combo = ttk.Combobox(
            language_frame,
            state="readonly",
            width=20,
            textvariable=self.language_var,
            values=[self._language_labels["en"], self._language_labels["tr"]],
        )
        self.language_combo.grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Button(language_frame, text=self._t("save_language"), command=self._save_language).grid(row=0, column=2, sticky=tk.W, padx=(10, 0), pady=4)

        targets_frame = ttk.LabelFrame(self.settings_content, text=self._t("tracked_targets"), padding=10)
        targets_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        server_columns = ("id", "name", "address", "enabled")
        self.server_tree = ttk.Treeview(targets_frame, columns=server_columns, show="headings", height=10)
        self.server_tree.heading("id", text=self._t("id"))
        self.server_tree.heading("name", text=self._t("name"))
        self.server_tree.heading("address", text=self._t("address"))
        self.server_tree.heading("enabled", text=self._t("enabled"))
        self.server_tree.column("id", width=60, anchor=tk.CENTER)
        self.server_tree.column("name", width=220, anchor=tk.W)
        self.server_tree.column("address", width=360, anchor=tk.W)
        self.server_tree.column("enabled", width=90, anchor=tk.CENTER)
        self.server_tree.bind("<<TreeviewSelect>>", self._on_server_select)
        self.server_tree.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(targets_frame)
        form.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(form, text=self._t("name")).grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.server_name_entry = ttk.Entry(form, textvariable=self.server_name_var, width=28)
        self.server_name_entry.grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Label(form, text=self._t("address")).grid(row=0, column=2, sticky=tk.W, padx=(20, 8), pady=4)
        self.server_address_entry = ttk.Entry(form, textvariable=self.server_address_var, width=40)
        self.server_address_entry.grid(row=0, column=3, sticky=tk.W, pady=4)
        ttk.Checkbutton(form, text=self._t("enabled"), variable=self.server_enabled_var).grid(row=0, column=4, padx=(20, 0), pady=4)

        buttons = ttk.Frame(form)
        buttons.grid(row=1, column=0, columnspan=5, sticky=tk.W, pady=(8, 0))
        ttk.Button(buttons, text=self._t("save_target"), command=self._save_server).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self._t("delete_target"), command=self._delete_server).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self._t("clear_form"), command=self._clear_server_form).pack(side=tk.LEFT)

        fan_frame = ttk.LabelFrame(self.settings_content, text=self._t("fan_settings"), padding=10)
        fan_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(fan_frame, text=self._t("fan_settings_info")).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))
        ttk.Label(fan_frame, text=self._t("gpio_pin")).grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.fan_pin_entry = ttk.Entry(fan_frame, textvariable=self.fan_pin_var, width=10)
        self.fan_pin_entry.grid(row=1, column=1, sticky=tk.W, pady=4)
        ttk.Label(fan_frame, text=self._t("temp_25")).grid(row=1, column=2, sticky=tk.W, padx=(20, 8), pady=4)
        self.fan_min_temp_entry = ttk.Entry(fan_frame, textvariable=self.fan_min_temp_var, width=10)
        self.fan_min_temp_entry.grid(row=1, column=3, sticky=tk.W, pady=4)
        ttk.Label(fan_frame, text=self._t("temp_100")).grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.fan_max_temp_entry = ttk.Entry(fan_frame, textvariable=self.fan_max_temp_var, width=10)
        self.fan_max_temp_entry.grid(row=2, column=1, sticky=tk.W, pady=4)
        ttk.Label(fan_frame, text=self._t("poll_interval")).grid(row=2, column=2, sticky=tk.W, padx=(20, 8), pady=4)
        self.fan_poll_interval_entry = ttk.Entry(fan_frame, textvariable=self.fan_poll_interval_var, width=10)
        self.fan_poll_interval_entry.grid(row=2, column=3, sticky=tk.W, pady=4)
        ttk.Button(fan_frame, text=self._t("save_fan_settings"), command=self._save_fan_settings).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(10, 0))

        telegram_frame = ttk.LabelFrame(self.settings_content, text=self._t("telegram_settings"), padding=10)
        telegram_frame.pack(fill=tk.X)
        ttk.Label(telegram_frame, text=self._t("bot_token")).grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.telegram_token_entry = ttk.Entry(telegram_frame, textvariable=self.telegram_token_var, width=72)
        self.telegram_token_entry.grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Label(telegram_frame, text=self._t("chat_user_id")).grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.telegram_chat_ids_entry = ttk.Entry(telegram_frame, textvariable=self.telegram_chat_ids_var, width=42)
        self.telegram_chat_ids_entry.grid(row=1, column=1, sticky=tk.W, pady=4)
        ttk.Label(telegram_frame, text=self._t("use_commas")).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
        button_row = ttk.Frame(telegram_frame)
        button_row.grid(row=3, column=0, columnspan=2, sticky=tk.W)
        ttk.Button(button_row, text=self._t("save_telegram_settings"), command=self._save_telegram_settings).pack(side=tk.LEFT)
        ttk.Button(button_row, text=self._t("send_test_message"), command=self._send_test_message).pack(side=tk.LEFT, padx=(8, 0))

    def _refresh_ui(self) -> None:
        snapshot = self.app.get_dashboard_snapshot()
        report = snapshot["report"]
        fan = snapshot["fan"]
        fan_settings = snapshot["fan_settings"]
        telegram_settings = snapshot["telegram_settings"]
        servers_config = snapshot["servers_config"]
        jobs = snapshot["jobs"]
        current_language = snapshot["language"]

        self._language_labels = {"en": self._t("english"), "tr": self._t("turkish")}
        self._language_codes_by_label = {value: key for key, value in self._language_labels.items()}
        self.language_var.set(self._language_labels.get(current_language, self._language_labels["en"]))

        self.status_var.set(
            self._t(
                "last_refresh_status",
                now=snapshot["now"],
                count=len(report["servers"]),
                uptime=report["overall_24h"].percentage,
            )
        )

        temp = fan["last_temp_c"]
        temp_text = f"{temp:.1f}°C" if isinstance(temp, (float, int)) else self._t("not_applicable")
        availability = self._t("gpio_ready") if fan["gpio_ready"] else self._t("gpio_unavailable")
        extra = self._t("fan_error_suffix", error=fan["last_error"]) if fan["last_error"] else ""
        self.fan_var.set(
            self._t(
                "fan_status_line",
                speed=fan["current_speed_percent"],
                temp=temp_text,
                pin=fan["pin"],
                min_temp=fan["min_temp_c"],
                max_temp=fan["max_temp_c"],
                availability=availability,
                extra=extra,
            )
        )

        self.next_jobs_var.set(
            " | ".join(f"{job['description']}: {job['next_run']}" for job in jobs) if jobs else self._t("no_scheduled_jobs")
        )

        self._set_text(
            self.summary_text,
            "\n".join(
                [
                    self._t("overall_24h_uptime", value=report["overall_24h"].percentage),
                    self._t("overall_7d_uptime", value=report["overall_7d"].percentage),
                    self._t("overall_uptime_line", value=report["overall_all"].percentage),
                    self._t("failures_24h", value=report["failures_total_24h"]),
                    self._t("failures_7d", value=report["failures_total_7d"]),
                ]
            ),
        )

        for item in self.tree.get_children():
            self.tree.delete(item)

        error_lines: list[str] = []
        for server in report["servers"]:
            is_up = server["is_up"]
            tag = "unknown"
            status_label = self._t("language_column_value", emoji="⚪", label=self._t("unknown"))
            if is_up is True:
                tag = "up"
                status_label = self._t("language_column_value", emoji="🟢", label=self._t("online"))
            elif is_up is False:
                tag = "down"
                status_label = self._t("language_column_value", emoji="🔴", label=self._t("offline"))

            if server["http_ok"] is False or (isinstance(server["ssl_days_left"], int) and server["ssl_days_left"] < 0):
                tag = "down"
                if is_up is not False:
                    status_label = self._t("language_column_value", emoji="🔴", label=self._t("attention"))

            latency = server["latency_ms"]
            latency_text = f"{latency} ms" if latency is not None else "-"
            self.tree.insert(
                "",
                tk.END,
                values=(
                    status_label,
                    server["name"],
                    server["address"],
                    latency_text,
                    self._format_http(server),
                    self._format_ssl(server),
                    f"{server['uptime_24h'].percentage:.1f}%",
                    f"{server['uptime_7d'].percentage:.1f}%",
                    f"{server['uptime_all'].percentage:.1f}%",
                    server["last_checked_at"] or "-",
                ),
                tags=(tag,),
            )
            if server["error"]:
                error_lines.append(f"{server['name']}: {server['error']}")
            if server["http_error"] and server["http_status_code"] is None:
                error_lines.append(f"{server['name']} HTTP: {server['http_error']}")
            if server["ssl_error"]:
                error_lines.append(f"{server['name']} SSL: {server['ssl_error']}")

        self._set_text(self.error_text, "\n".join(error_lines or [self._t("no_active_errors")]))

        self._refresh_server_tree(servers_config)
        if self.root.focus_get() not in {
            self.fan_pin_entry,
            self.fan_min_temp_entry,
            self.fan_max_temp_entry,
            self.fan_poll_interval_entry,
        }:
            self._populate_fan_form(fan_settings)

        if self.root.focus_get() not in {self.telegram_token_entry, self.telegram_chat_ids_entry}:
            self.telegram_token_var.set(str(telegram_settings["token"]))
            self.telegram_chat_ids_var.set(str(telegram_settings["chat_ids_raw"]))

        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
        self._refresh_after_id = self.root.after(self.refresh_ms, self._refresh_ui)

    def _refresh_server_tree(self, servers_config) -> None:
        existing_selection = self._selected_server_id
        for item in self.server_tree.get_children():
            self.server_tree.delete(item)

        for server in servers_config:
            self.server_tree.insert(
                "",
                tk.END,
                iid=str(server.id),
                values=(server.id, server.name, server.address, self._t("yes") if server.enabled else self._t("no")),
            )

        if existing_selection is not None and self.server_tree.exists(str(existing_selection)):
            self.server_tree.selection_set(str(existing_selection))

    def _populate_fan_form(self, fan_settings) -> None:
        self.fan_pin_var.set(str(fan_settings.pin))
        self.fan_min_temp_var.set(str(fan_settings.min_temp_c))
        self.fan_max_temp_var.set(str(fan_settings.max_temp_c))
        self.fan_poll_interval_var.set(str(fan_settings.poll_interval_seconds))

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def _format_http(self, server) -> str:
        status_code = server["http_status_code"]
        http_ok = server["http_ok"]
        http_error = server["http_error"]

        if status_code is not None:
            return f"{'🟢' if http_ok else '🔴'} {status_code}"
        if http_error:
            return f"🔴 {self._t('error_short')}"
        return f"⚪ {self._t('not_applicable')}"

    def _format_ssl(self, server) -> str:
        days_left = server["ssl_days_left"]
        ssl_error = server["ssl_error"]

        if isinstance(days_left, int):
            if days_left < 0:
                return f"🔴 {self._t('expired_short')}"
            if days_left <= 30:
                return f"🟠 {self._t('days_left_short', days=days_left)}"
            return f"🟢 {self._t('days_left_short', days=days_left)}"
        if ssl_error:
            return f"🔴 {self._t('error_short')}"
        return f"⚪ {self._t('not_applicable')}"

    def _run_now(self) -> None:
        threading.Thread(target=self.app.run_once, kwargs={"send_notification": True, "title": self._t("manual_server_report")}, daemon=True).start()

    def _run_daily(self) -> None:
        threading.Thread(target=self.app.run_daily_summary, kwargs={"send_notification": True}, daemon=True).start()

    def _run_weekly(self) -> None:
        threading.Thread(target=self.app.run_weekly_summary, kwargs={"send_notification": True}, daemon=True).start()

    def _on_server_select(self, _event=None) -> None:
        selected = self.server_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        self._selected_server_id = int(item_id)
        values = self.server_tree.item(item_id, "values")
        self.server_name_var.set(values[1])
        self.server_address_var.set(values[2])
        self.server_enabled_var.set(values[3] == self._t("yes"))

    def _clear_server_form(self) -> None:
        self._selected_server_id = None
        self.server_name_var.set("")
        self.server_address_var.set("")
        self.server_enabled_var.set(True)
        self.server_tree.selection_remove(self.server_tree.selection())

    def _save_server(self) -> None:
        ok, message = self.app.save_server(
            name=self.server_name_var.get(),
            address=self.server_address_var.get(),
            enabled=self.server_enabled_var.get(),
            server_id=self._selected_server_id,
        )
        self.settings_status_var.set(message)
        if ok:
            self._clear_server_form()
            self._refresh_ui()
        else:
            messagebox.showerror(self._t("save_target_title"), message)

    def _delete_server(self) -> None:
        if self._selected_server_id is None:
            messagebox.showwarning(self._t("delete_target_title"), self._t("delete_target_select_first"))
            return
        if not messagebox.askyesno(self._t("delete_target_title"), self._t("delete_target_confirm")):
            return
        _, message = self.app.delete_server(self._selected_server_id)
        self.settings_status_var.set(message)
        self._clear_server_form()
        self._refresh_ui()

    def _save_fan_settings(self) -> None:
        try:
            pin = int(self.fan_pin_var.get().strip())
            min_temp = float(self.fan_min_temp_var.get().strip())
            max_temp = float(self.fan_max_temp_var.get().strip())
            poll_interval = int(self.fan_poll_interval_var.get().strip())
        except ValueError:
            messagebox.showerror(self._t("fan_settings_title"), self._t("fan_settings_numeric"))
            return

        ok, message = self.app.save_fan_settings(
            pin=pin,
            min_temp_c=min_temp,
            max_temp_c=max_temp,
            poll_interval_seconds=poll_interval,
        )
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror(self._t("fan_settings_title"), message)
            return
        self._refresh_ui()

    def _save_telegram_settings(self) -> None:
        ok, message = self.app.save_telegram_settings(
            token=self.telegram_token_var.get(),
            chat_ids_raw=self.telegram_chat_ids_var.get(),
        )
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror(self._t("telegram_settings"), message)
            return
        self._refresh_ui()

    def _send_test_message(self) -> None:
        ok, message = self.app.save_telegram_settings(
            token=self.telegram_token_var.get(),
            chat_ids_raw=self.telegram_chat_ids_var.get(),
        )
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror(self._t("telegram_test_title"), message)
            return

        ok, message = self.app.send_test_telegram_message()
        self.settings_status_var.set(message)
        if ok:
            messagebox.showinfo(self._t("telegram_test_title"), message)
            return
        messagebox.showerror(self._t("telegram_test_title"), message)

    def _save_language(self) -> None:
        selected_label = self.language_var.get().strip()
        language_code = self._language_codes_by_label.get(selected_label, "en")
        ok, message = self.app.save_language(language_code)
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror(self._t("language_settings"), message)
            return
        self._rebuild_ui()
        self._refresh_ui()

    def _rebuild_ui(self) -> None:
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        self._language_labels = {"en": self._t("english"), "tr": self._t("turkish")}
        self._language_codes_by_label = {value: key for key, value in self._language_labels.items()}
        for child in self.root.winfo_children():
            child.destroy()
        self._build_layout()

    def _on_mouse_wheel(self, event) -> None:
        if hasattr(self, "settings_canvas"):
            self.settings_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_close(self) -> None:
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
        self.app.stop()
        self.root.destroy()

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.app.get_language(), key, **kwargs)
