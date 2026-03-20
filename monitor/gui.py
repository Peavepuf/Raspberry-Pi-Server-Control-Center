from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk


class MonitorDashboard:
    def __init__(self, app) -> None:
        self.app = app
        self.root = tk.Tk()
        self.root.title("Raspberry Pi Server Control Center")
        self.root.geometry("1450x860")
        self.root.minsize(1240, 780)
        self.refresh_ms = max(1000, int(self.app.config.gui_refresh_seconds * 1000))
        self._refresh_after_id: str | None = None
        self._selected_server_id: int | None = None

        self.status_var = tk.StringVar(value="Starting...")
        self.fan_var = tk.StringVar(value="Fan status: loading")
        self.next_jobs_var = tk.StringVar(value="Scheduled jobs are loading...")
        self.settings_status_var = tk.StringVar(value="Settings are ready.")

        self.server_name_var = tk.StringVar()
        self.server_address_var = tk.StringVar()
        self.server_enabled_var = tk.BooleanVar(value=True)

        self.fan_pin_var = tk.StringVar()
        self.fan_min_temp_var = tk.StringVar()
        self.fan_max_temp_var = tk.StringVar()
        self.fan_poll_interval_var = tk.StringVar()
        self.telegram_token_var = tk.StringVar()
        self.telegram_chat_ids_var = tk.StringVar()

        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> int:
        self.app.start_scheduler_thread()
        self._refresh_ui()
        self.root.mainloop()
        return 0

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text="Raspberry Pi Server Control Center", font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(header, textvariable=self.status_var).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(header, textvariable=self.fan_var, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(header, textvariable=self.next_jobs_var).pack(anchor=tk.W, pady=(2, 0))

        top_buttons = ttk.Frame(container)
        top_buttons.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(top_buttons, text="Run Check Now", command=self._run_now).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_buttons, text="Send Daily Summary", command=self._run_daily).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_buttons, text="Send Weekly Summary", command=self._run_weekly).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_buttons, text="Refresh", command=self._refresh_ui).pack(side=tk.LEFT)

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.dashboard_tab = ttk.Frame(notebook, padding=10)
        self.settings_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.dashboard_tab, text="Dashboard")
        notebook.add(self.settings_tab, text="Settings")

        self._build_dashboard_tab()
        self._build_settings_tab()

    def _build_dashboard_tab(self) -> None:
        summary_frame = ttk.LabelFrame(self.dashboard_tab, text="Overview", padding=10)
        summary_frame.pack(fill=tk.X, pady=(0, 12))
        self.summary_text = tk.Text(summary_frame, height=8, wrap="word")
        self.summary_text.pack(fill=tk.X)
        self.summary_text.configure(state=tk.DISABLED)

        table_frame = ttk.LabelFrame(self.dashboard_tab, text="Tracked Targets", padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("status", "name", "address", "latency", "http", "ssl", "uptime24", "uptime7", "uptimeall", "last")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "status": "Status",
            "name": "Name",
            "address": "Address / URL / IP",
            "latency": "Latency",
            "http": "HTTP/HTTPS",
            "ssl": "SSL",
            "uptime24": "24h Uptime",
            "uptime7": "7d Uptime",
            "uptimeall": "Overall Uptime",
            "last": "Last Check",
        }
        widths = {
            "status": 110,
            "name": 190,
            "address": 260,
            "latency": 90,
            "http": 150,
            "ssl": 140,
            "uptime24": 110,
            "uptime7": 110,
            "uptimeall": 110,
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

        details_frame = ttk.LabelFrame(self.dashboard_tab, text="Errors and Details", padding=10)
        details_frame.pack(fill=tk.BOTH, expand=False, pady=(12, 0))
        self.error_text = tk.Text(details_frame, height=8, wrap="word")
        self.error_text.pack(fill=tk.BOTH, expand=True)
        self.error_text.configure(state=tk.DISABLED)

    def _build_settings_tab(self) -> None:
        ttk.Label(self.settings_tab, textvariable=self.settings_status_var, foreground="#004085").pack(anchor=tk.W, pady=(0, 10))

        targets_frame = ttk.LabelFrame(self.settings_tab, text="Tracked Targets", padding=10)
        targets_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        server_columns = ("id", "name", "address", "enabled")
        self.server_tree = ttk.Treeview(targets_frame, columns=server_columns, show="headings", height=10)
        self.server_tree.heading("id", text="ID")
        self.server_tree.heading("name", text="Name")
        self.server_tree.heading("address", text="Address / URL / IP")
        self.server_tree.heading("enabled", text="Enabled")
        self.server_tree.column("id", width=60, anchor=tk.CENTER)
        self.server_tree.column("name", width=220, anchor=tk.W)
        self.server_tree.column("address", width=360, anchor=tk.W)
        self.server_tree.column("enabled", width=90, anchor=tk.CENTER)
        self.server_tree.bind("<<TreeviewSelect>>", self._on_server_select)
        self.server_tree.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(targets_frame)
        form.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(form, text="Name").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.server_name_entry = ttk.Entry(form, textvariable=self.server_name_var, width=28)
        self.server_name_entry.grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Label(form, text="Address / URL / IP").grid(row=0, column=2, sticky=tk.W, padx=(20, 8), pady=4)
        self.server_address_entry = ttk.Entry(form, textvariable=self.server_address_var, width=40)
        self.server_address_entry.grid(row=0, column=3, sticky=tk.W, pady=4)
        ttk.Checkbutton(form, text="Enabled", variable=self.server_enabled_var).grid(row=0, column=4, padx=(20, 0), pady=4)

        buttons = ttk.Frame(form)
        buttons.grid(row=1, column=0, columnspan=5, sticky=tk.W, pady=(8, 0))
        ttk.Button(buttons, text="Save Target", command=self._save_server).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Delete Target", command=self._delete_server).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Clear Form", command=self._clear_server_form).pack(side=tk.LEFT)

        fan_frame = ttk.LabelFrame(self.settings_tab, text="Fan Settings", padding=10)
        fan_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(
            fan_frame,
            text="At the 25% temperature the fan starts at 25% speed. At the 100% temperature it reaches full speed.",
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))

        ttk.Label(fan_frame, text="GPIO Pin").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.fan_pin_entry = ttk.Entry(fan_frame, textvariable=self.fan_pin_var, width=10)
        self.fan_pin_entry.grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(fan_frame, text="25% Temperature (°C)").grid(row=1, column=2, sticky=tk.W, padx=(20, 8), pady=4)
        self.fan_min_temp_entry = ttk.Entry(fan_frame, textvariable=self.fan_min_temp_var, width=10)
        self.fan_min_temp_entry.grid(row=1, column=3, sticky=tk.W, pady=4)

        ttk.Label(fan_frame, text="100% Temperature (°C)").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.fan_max_temp_entry = ttk.Entry(fan_frame, textvariable=self.fan_max_temp_var, width=10)
        self.fan_max_temp_entry.grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Label(fan_frame, text="Polling Interval (sec)").grid(row=2, column=2, sticky=tk.W, padx=(20, 8), pady=4)
        self.fan_poll_interval_entry = ttk.Entry(fan_frame, textvariable=self.fan_poll_interval_var, width=10)
        self.fan_poll_interval_entry.grid(row=2, column=3, sticky=tk.W, pady=4)

        ttk.Button(fan_frame, text="Save Fan Settings", command=self._save_fan_settings).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(10, 0))

        telegram_frame = ttk.LabelFrame(self.settings_tab, text="Telegram Settings", padding=10)
        telegram_frame.pack(fill=tk.X)

        ttk.Label(telegram_frame, text="Bot Token").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.telegram_token_entry = ttk.Entry(telegram_frame, textvariable=self.telegram_token_var, width=72)
        self.telegram_token_entry.grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(telegram_frame, text="Chat / User ID").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.telegram_chat_ids_entry = ttk.Entry(telegram_frame, textvariable=self.telegram_chat_ids_var, width=42)
        self.telegram_chat_ids_entry.grid(row=1, column=1, sticky=tk.W, pady=4)
        ttk.Label(telegram_frame, text="Use commas to separate multiple IDs.").grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        button_row = ttk.Frame(telegram_frame)
        button_row.grid(row=3, column=0, columnspan=2, sticky=tk.W)
        ttk.Button(button_row, text="Save Telegram Settings", command=self._save_telegram_settings).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Send Test Message", command=self._send_test_message).pack(side=tk.LEFT, padx=(8, 0))

    def _refresh_ui(self) -> None:
        snapshot = self.app.get_dashboard_snapshot()
        report = snapshot["report"]
        fan = snapshot["fan"]
        fan_settings = snapshot["fan_settings"]
        telegram_settings = snapshot["telegram_settings"]
        servers_config = snapshot["servers_config"]
        jobs = snapshot["jobs"]

        self.status_var.set(
            f"Last refresh: {snapshot['now']} | Active targets: {len(report['servers'])} | Overall 24h uptime: {report['overall_24h'].percentage:.1f}%"
        )

        temp = fan["last_temp_c"]
        temp_text = f"{temp:.1f}°C" if isinstance(temp, (float, int)) else "unavailable"
        availability = "GPIO ready" if fan["gpio_ready"] else "GPIO unavailable"
        extra = f" | Error: {fan['last_error']}" if fan["last_error"] else ""
        self.fan_var.set(
            f"Fan: {fan['current_speed_percent']}% | CPU: {temp_text} | GPIO{fan['pin']} | 25% @ {fan['min_temp_c']}°C | 100% @ {fan['max_temp_c']}°C | {availability}{extra}"
        )

        self.next_jobs_var.set(" | ".join(f"{job['name']}: {job['next_run']}" for job in jobs) if jobs else "No scheduled jobs.")

        self._set_text(
            self.summary_text,
            "\n".join(
                [
                    f"Overall 24h uptime: {report['overall_24h'].percentage:.1f}%",
                    f"Overall 7d uptime: {report['overall_7d'].percentage:.1f}%",
                    f"Overall uptime: {report['overall_all'].percentage:.1f}%",
                    f"24h failures: {report['failures_total_24h']}",
                    f"7d failures: {report['failures_total_7d']}",
                ]
            ),
        )

        for item in self.tree.get_children():
            self.tree.delete(item)

        error_lines: list[str] = []
        for server in report["servers"]:
            is_up = server["is_up"]
            tag = "unknown"
            status_label = "⚪ Unknown"
            if is_up is True:
                tag = "up"
                status_label = "🟢 Online"
            elif is_up is False:
                tag = "down"
                status_label = "🔴 Offline"

            if server["http_ok"] is False or (isinstance(server["ssl_days_left"], int) and server["ssl_days_left"] < 0):
                tag = "down"
                if is_up is not False:
                    status_label = "🔴 Attention"

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

        self._set_text(self.error_text, "\n".join(error_lines or ["No active errors."]))

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
                values=(server.id, server.name, server.address, "Yes" if server.enabled else "No"),
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
            return "🔴 Error"
        return "⚪ N/A"

    def _format_ssl(self, server) -> str:
        days_left = server["ssl_days_left"]
        ssl_error = server["ssl_error"]

        if isinstance(days_left, int):
            if days_left < 0:
                return "🔴 Expired"
            if days_left <= 30:
                return f"🟠 {days_left} day(s)"
            return f"🟢 {days_left} day(s)"
        if ssl_error:
            return "🔴 Error"
        return "⚪ N/A"

    def _run_now(self) -> None:
        threading.Thread(target=self.app.run_once, kwargs={"send_notification": True, "title": "Manual server report"}, daemon=True).start()

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
        self.server_enabled_var.set(values[3] == "Yes")

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
            messagebox.showerror("Save Target", message)

    def _delete_server(self) -> None:
        if self._selected_server_id is None:
            messagebox.showwarning("Delete Target", "Select a target from the list first.")
            return
        if not messagebox.askyesno("Delete Target", "Do you want to delete the selected target?"):
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
            messagebox.showerror("Fan Settings", "All fan settings must be numeric.")
            return

        ok, message = self.app.save_fan_settings(
            pin=pin,
            min_temp_c=min_temp,
            max_temp_c=max_temp,
            poll_interval_seconds=poll_interval,
        )
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror("Fan Settings", message)
            return
        self._refresh_ui()

    def _save_telegram_settings(self) -> None:
        ok, message = self.app.save_telegram_settings(
            token=self.telegram_token_var.get(),
            chat_ids_raw=self.telegram_chat_ids_var.get(),
        )
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror("Telegram Settings", message)
            return
        self._refresh_ui()

    def _send_test_message(self) -> None:
        ok, message = self.app.save_telegram_settings(
            token=self.telegram_token_var.get(),
            chat_ids_raw=self.telegram_chat_ids_var.get(),
        )
        self.settings_status_var.set(message)
        if not ok:
            messagebox.showerror("Telegram Test", message)
            return

        ok, message = self.app.send_test_telegram_message()
        self.settings_status_var.set(message)
        if ok:
            messagebox.showinfo("Telegram Test", message)
            return
        messagebox.showerror("Telegram Test", message)

    def _on_close(self) -> None:
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
        self.app.stop()
        self.root.destroy()
