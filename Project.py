import os
from dotenv import load_dotenv
import json
import csv
import zipfile
from pathlib import Path
import pandas as pd
import lxml.etree as ET

import tkinter as tk
from tkinter import filedialog

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Button, Input, Label, Select, Static, Log, Markdown, ProgressBar
from textual.screen import Screen
from textual.binding import Binding

from openai import OpenAI

DB_FILE = "users.json"

def load_users():
    if not os.path.exists(DB_FILE):
        default_users = {"admin": "123"}
        with open(DB_FILE, "w") as file:
            json.dump(default_users, file)
        return default_users
    with open(DB_FILE, "r") as file:
        return json.load(file)

def save_users(users_dict):
    with open(DB_FILE, "w") as file:
        json.dump(users_dict, file)

def parse_apple_health(zip_path, log_widget):
    project_folder = Path(__file__).parent.absolute()
    zip_path = Path(zip_path)
    output_folder = project_folder / zip_path.stem
    
    if not output_folder.exists():
        os.makedirs(output_folder)
        log_widget.update(f"Created directory: {output_folder}")

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            xml_files = [f for f in z.namelist() if f.endswith('.xml') and "cda" not in f.lower()]

            for xml_name in xml_files:
                log_widget.update(f"Analyzing {xml_name}...")
                
                outputs, writers = {}, {}
                try: 
                    progress_bar= log_widget.app.query_one("#zip_progress", ProgressBar)
                    progress_bar.progress = 0
                except:
                    progress_bar = None

                with z.open(xml_name) as f:
                    context = ET.iterparse(f, events=('end',), tag=('Record', 'Workout', 'ActivitySummary'))
                    count = 0
                    for event, elem in context:
                        tag_name = elem.tag
                        data = dict(elem.attrib)
                        if data:
                            if tag_name not in outputs:
                                csv_name = output_folder / f"{tag_name}.csv"
                                f_out = open(csv_name, 'w', newline='', encoding='utf-8-sig')
                                writer = csv.DictWriter(f_out, fieldnames=data.keys(), extrasaction='ignore')
                                writer.writeheader()
                                outputs[tag_name] = f_out
                                writers[tag_name] = writer

                            writers[tag_name].writerow(data)
                            count += 1
                            if count % 1000 == 0 and progress_bar:
                                xml_info = z.getinfo(xml_name)
                                total_bytes = xml_info.file_size
                                if total_bytes > 0:
                                    percent = int((f.tell() / total_bytes)*100)
                                    progress_bar.progress = percent
                        
                        elem.clear()
                        while elem.getprevious() is not None:
                            del elem.getparent()[0]

                for f_out in outputs.values():
                    f_out.close()
                log_widget.update(f"Success: Generated files in /{output_folder.name}/")
        return output_folder
    except Exception as e:
        log_widget.update(f"Error parsing zip: {e}")
        return None

def get_health_summary(folder_path):
    try:
        folder_path = Path(folder_path)
        record_file = folder_path / "Record.csv"
        if not record_file.exists():
            return None

        df = pd.read_csv(record_file, usecols=['type', 'startDate', 'value'], dtype=str)
        df_steps = df[df['type'] == 'HKQuantityTypeIdentifierStepCount'].copy()
        df_steps['startDate'] = pd.to_datetime(df_steps['startDate'], errors='coerce')
        df_steps['value'] = pd.to_numeric(df_steps['value'], errors='coerce')

        if not df_steps.empty:
            latest_date = df_steps['startDate'].dt.date.max()
            total_steps = df_steps[df_steps['startDate'].dt.date == latest_date]['value'].sum()
            return f"Date: {latest_date}, Steps: {int(total_steps)}"
        return "No step data found."
    except:
        return None

class LoginScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Label("🥗 WELCOME TO FRIDGEFIT 🥗", id="title"),
            Label("Username:", classes="form-label"),
            Input(placeholder="Enter username", id="username_input"),
            Label("Password:", classes="form-label"),
            Input(placeholder="Enter password", password=True, id="password_input"),
            Horizontal(
                Button("Log In", variant="primary", id="login_btn"),
                Button("Register", variant="default", id="register_btn"), 
                id="btn_row"
            ),
            Label("", id="msg_label"),
            id="login_form"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        users = load_users()
        username = self.query_one("#username_input", Input).value.strip()
        password = self.query_one("#password_input", Input).value.strip()
        msg = self.query_one("#msg_label", Label)

        if not username:
            msg.update("[red]Username cannot be empty![/red]")
            return

        if username.lower() == 'admin' and event.button.id == "login_btn":
            self.app.current_user = "admin"
            self.app.push_screen(DashboardScreen())
            return

        if event.button.id == "login_btn":
            if username not in users:
                msg.update("[red]Account not found! Please register first.[/red]")
            elif users[username] != password:
                msg.update("[red]Incorrect password![/red]")
            else:
                self.app.current_user = username
                self.app.push_screen(DashboardScreen())
                
        elif event.button.id == "register_btn":
            if username in users:
                msg.update("[red]Username already exists![/red]")
            elif len(password) < 8:
                msg.update("[red]Password must be at least 8 characters![/red]")
            else:
                users[username] = password
                save_users(users)
                msg.update("[green]Registration successful! You can now log in.[/green]")


class DashboardScreen(Screen):
    BINDINGS = [
        Binding("q", "logout", "Log Out", priority=True)
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Label(f"Active User: {self.app.current_user}", id="user_bar"),
            Label("1. Setup Your Goal & Ingredients", classes="section-title"),
            Select(
                options=[("Weight Loss", "Weight Loss"), ("Muscle Gain", "Muscle Gain"), ("Maintenance", "Maintenance")],
                prompt="Select Fitness Goal",
                id="goal_select"
            ),
            Input(placeholder="What's in your fridge? (e.g. Chicken, Broccoli)", id="ingredients_input"),
            
            Label("2. Apple Health Data (Optional)", classes="section-title"),
            
            Horizontal(
                Input(placeholder="Path to Apple Health export.zip", id="zip_path_input"),
                Button("📁 Choose File", variant="default", id="choose_file_btn"),
                id="file_input_row"
            ),
            
            Button("Process ZIP", variant="default", id="process_zip_btn"),
            ProgressBar(id="zip_progress",show_percentage=True, total= 100),
            Label("No file processed yet.", id="log_view"),
            
            Label("Manual Activity (If no ZIP)", classes="section-title"),
            Input(placeholder="e.g. Ran 10km, Sedentary", id="manual_activity"),
            
            Button("🚀 Generate AI Meal Plan", variant="success", id="generate_btn"),
            
            Label("🍽️ AI Recipe Result", classes="section-title"),
            Markdown("Your recipe will appear here...", id="recipe_output"),
            id="dashboard_container"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        log_view = self.query_one("#log_view", Label)
        zip_input = self.query_one("#zip_path_input", Input)
        
        if event.button.id == "choose_file_btn":
            
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True) 
            
            file_path = filedialog.askopenfilename(
                title="Choose Apple Health export.zip", 
                filetypes=[("ZIP files", "*.zip")]
            )
            root.destroy()
            
            if file_path:
                zip_input.value = file_path
                log_view.update(f"[green] Selected file: {file_path}[/green]")
            return

        elif event.button.id == "process_zip_btn":
            zip_path = zip_input.value.strip()
            if not zip_path or not os.path.exists(zip_path):
                log_view.update("[red]Error: Invalid zip file path.[/red]")
                return
            
            progress_bar=self.query_one("#zip_progress", ProgressBar)
            progress_bar.display = True
            progress_bar.progress = 0

            log_view.update("Processing ZIP... This may take a while.")

            output_folder = parse_apple_health(zip_path, log_view)
            if output_folder:
                progress_bar.progress = 100
                summary = get_health_summary(output_folder)
                self.app.activity_data = f"Apple Health Data: {summary}"
                log_view.update(f"Data loaded: {summary}")

                def hide_bar():
                    progress_bar.display = False
                    self.set_timer(2.0, hide_bar)
                
        elif event.button.id == "generate_btn":
            self.run_worker(self.generate_recipe())

    async def generate_recipe(self):
        output = self.query_one("#recipe_output", Markdown)
        output.update("[yellow]Thinking... Calling DeepSeek API...[/yellow]")
        
        goal = self.query_one("#goal_select", Select).value
        ingredients = self.query_one("#ingredients_input", Input).value
        manual_act = self.query_one("#manual_activity", Input).value
        
        activity = self.app.activity_data if self.app.activity_data else manual_act
        
        if not goal or not ingredients:
            output.update("[red]Please select a goal and fill in your ingredients![/red]")
            return

        load_dotenv()

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            output.update("[red]Error: DEEPSEEK_API_KEY environment variable not found.[/red]")
            return

        prompt = f"""
        You are an expert sports nutritionist and master chef for the app FridgeFit.
        User Data:
        - Available Ingredients: {ingredients}
        - Primary Fitness Goal: {goal}
        - Today's Energy Expenditure: {activity}

        Please provide a personalized recipe adjusting macros/calories based on their exact energy expenditure today. Include cooking instructions and briefly explain why this fits their goal and activity level. Use markdown.
        """
        
        try:
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com" # 指向 DeepSeek
            )

            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a helpful and professional health assistant."},
                    {"role": "user", "content": prompt}
                ],
                stream=False
            )
            output.update(response.choices[0].message.content)
            
        except Exception as e:
            output.update(f"[red]DeepSeek API connection failed: {e}[/red]")

    def action_logout(self) -> None:
        self.app.current_user = None
        self.app.activity_data = ""
        self.app.pop_screen()

class FridgeFitApp(App):
    CSS = """
    Screen {
        align: center middle;
    }
    #login_form {
        width: 60;
        height: auto;
        border: solid green;
        background: $boost;
        padding: 1 2;
    }
    #title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
        color: lightgreen;
    }
    .form-label {
        margin-top: 1;
        text-style: bold;
    }
    #btn_row {
        margin-top: 1;
        height: 3;
        align: center middle;
    }
    #btn_row Button {
        margin: 0 1;
    }
    #msg_label {
        margin-top: 1;
        text-align: center;
    }
    
    #dashboard_container {
        width: 100;
        height: 100%;
        padding: 1 2;
        border: solid cyan;
    }
    #user_bar {
        background: $accent;
        color: white;
        text-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }
    .section-title {
        color: yellow;
        text-style: bold;
        margin-top: 1;
    }
    
    #file_input_row {
        height: auto;
        margin: 1 0;
    }
    #file_input_row Input {
        width: 70%;
    }
    #file_input_row Button {
        width: 30%;
    }

    #log_view {
        height: 5;
        background: $panel;
        border: solid grey; 
        margin: 1 0;
    }
    #recipe_output {
        height:20;
        border: round green;
        background: $boost;
        margin: 1 1;
        overflow-y: scroll;
        width: 100%;
    }
    #zip_progress {
        display: none;
        margin:1 0;
    }
    """
    
    current_user = None
    activity_data = ""

    def on_mount(self) -> None:
        self.push_screen(LoginScreen())

if __name__ == "__main__":
    app = FridgeFitApp()
    app.run()
