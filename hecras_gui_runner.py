# -*- coding: utf-8 -*-
"""
Created on Mon Feb 16 10:21:32 2026

@author: Siamak.Farrokhzadeh
"""

import os
import time
import shutil
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import multiprocessing
from multiprocessing import Process, Queue
import win32com.client
import pythoncom
import threading
import sys
import queue
import re

class HECRASParallelRunnerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("HECRAS Parallel Runner v2.1")
        self.root.geometry("900x800")
        
        # Variables to store user inputs
        self.project_path = tk.StringVar()
        self.dss_path = tk.StringVar()
        
        # Queue for communication between threads
        self.log_queue = queue.Queue()
        
        # Create GUI
        self.create_widgets()
        
        # Start checking the queue for messages
        self.process_log_queue()
        
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="HECRAS Parallel Runner", 
                                 font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=10)
        
        # Project File Selection
        ttk.Label(main_frame, text="HECRAS Project File (.prj):").grid(row=1, column=0, 
                                                                       sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.project_path, width=50).grid(row=1, column=1, 
                                                                              padx=5, pady=5)
        ttk.Button(main_frame, text="Browse...", 
                  command=self.browse_project).grid(row=1, column=2, padx=5, pady=5)
        
        # DSS File Selection
        ttk.Label(main_frame, text="DSS File Path:").grid(row=2, column=0, 
                                                          sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.dss_path, width=50).grid(row=2, column=1, 
                                                                          padx=5, pady=5)
        ttk.Button(main_frame, text="Browse...", 
                  command=self.browse_dss).grid(row=2, column=2, padx=5, pady=5)
        
        # Plan Management Frame
        plan_frame = ttk.LabelFrame(main_frame, text="Plan Configuration", padding="10")
        plan_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # Plan input fields
        ttk.Label(plan_frame, text="Plan Name:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.plan_name_entry = ttk.Entry(plan_frame, width=20)
        self.plan_name_entry.grid(row=0, column=1, padx=5, pady=5, columnspan=2)
        
        # Component suffixes
        ttk.Label(plan_frame, text="Component Suffixes:", font=('Arial', 10, 'bold')).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(10,5))
        
        # Plan suffix
        ttk.Label(plan_frame, text="Plan Suffix (.p??):").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.plan_suffix_entry = ttk.Entry(plan_frame, width=10)
        self.plan_suffix_entry.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(plan_frame, text="e.g., 03").grid(row=2, column=2, sticky=tk.W, padx=2)
        
        # Geometry suffix
        ttk.Label(plan_frame, text="Geometry Suffix (.g??):").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.geom_suffix_entry = ttk.Entry(plan_frame, width=10)
        self.geom_suffix_entry.grid(row=3, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(plan_frame, text="e.g., 01").grid(row=3, column=2, sticky=tk.W, padx=2)
        
        # Unsteady flow suffix
        ttk.Label(plan_frame, text="Unsteady Flow Suffix (.u??):").grid(row=4, column=0, sticky=tk.W, padx=5)
        self.flow_suffix_entry = ttk.Entry(plan_frame, width=10)
        self.flow_suffix_entry.grid(row=4, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(plan_frame, text="e.g., 05").grid(row=4, column=2, sticky=tk.W, padx=2)
        
        # Additional suffixes (optional)
        ttk.Label(plan_frame, text="Other Suffixes (optional):").grid(row=5, column=0, sticky=tk.W, padx=5)
        self.other_suffixes_entry = ttk.Entry(plan_frame, width=30)
        self.other_suffixes_entry.grid(row=5, column=1, padx=5, pady=2, columnspan=2, sticky=tk.W)
        ttk.Label(plan_frame, text="Comma-separated: p,x,c,b").grid(row=6, column=1, columnspan=2, sticky=tk.W, padx=5)
        
        # Add plan button
        ttk.Button(plan_frame, text="Add Plan Configuration", 
                  command=self.add_plan).grid(row=7, column=0, columnspan=3, pady=10)
        
        # Plans List
        ttk.Label(plan_frame, text="Configured Plans:").grid(row=8, column=0, columnspan=3, 
                                                             sticky=tk.W, pady=5)
        
        # Treeview for plans with all components
        columns = ('Plan Name', 'Plan Suffix', 'Geom Suffix', 'Flow Suffix', 'Other')
        self.plan_tree = ttk.Treeview(plan_frame, columns=columns, show='headings', height=5)
        self.plan_tree.heading('Plan Name', text='Plan Name')
        self.plan_tree.heading('Plan Suffix', text='Plan Suf')
        self.plan_tree.heading('Geom Suffix', text='Geom Suf')
        self.plan_tree.heading('Flow Suffix', text='Flow Suf')
        self.plan_tree.heading('Other', text='Other Suffixes')
        
        # Set column widths
        self.plan_tree.column('Plan Name', width=150)
        self.plan_tree.column('Plan Suffix', width=70)
        self.plan_tree.column('Geom Suffix', width=70)
        self.plan_tree.column('Flow Suffix', width=70)
        self.plan_tree.column('Other', width=150)
        
        self.plan_tree.grid(row=9, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # Scrollbar for treeview
        scrollbar = ttk.Scrollbar(plan_frame, orient=tk.VERTICAL, command=self.plan_tree.yview)
        scrollbar.grid(row=9, column=2, sticky=(tk.N, tk.S))
        self.plan_tree.configure(yscrollcommand=scrollbar.set)
        
        # Buttons frame for plan management
        button_frame = ttk.Frame(plan_frame)
        button_frame.grid(row=10, column=0, columnspan=3, pady=5)
        
        ttk.Button(button_frame, text="Remove Selected", 
                  command=self.remove_plan).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear All", 
                  command=self.clear_plans).pack(side=tk.LEFT, padx=5)
        
        # Execution Options
        options_frame = ttk.LabelFrame(main_frame, text="Execution Options", padding="10")
        options_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        self.run_parallel = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Run plans in parallel", 
                       variable=self.run_parallel).grid(row=0, column=0, sticky=tk.W)
        
        self.cleanup_temp = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Clean up temporary files after completion", 
                       variable=self.cleanup_temp).grid(row=1, column=0, sticky=tk.W)
        
        # Execute Button
        self.execute_btn = ttk.Button(main_frame, text="EXECUTE SIMULATIONS", 
                                      command=self.execute_simulations, width=30)
        self.execute_btn.grid(row=5, column=0, columnspan=3, pady=20)
        
        # Progress Bar
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Log Output
        log_frame = ttk.LabelFrame(main_frame, text="Execution Log", padding="5")
        log_frame.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, width=100, height=15, 
                                                   font=('Courier', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Status Bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, 
                               relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Configure grid weights
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(7, weight=1)
        
    def process_log_queue(self):
        """Process messages from the log queue"""
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        finally:
            # Check again after 100ms
            self.root.after(100, self.process_log_queue)
        
    def browse_project(self):
        filename = filedialog.askopenfilename(
            title="Select HECRAS Project File",
            filetypes=[("Project files", "*.prj"), ("All files", "*.*")]
        )
        if filename:
            self.project_path.set(filename)
            self.log(f"Project selected: {filename}")
            
    def browse_dss(self):
        filename = filedialog.askopenfilename(
            title="Select DSS File",
            filetypes=[("DSS files", "*.dss"), ("All files", "*.*")]
        )
        if filename:
            self.dss_path.set(filename)
            self.log(f"DSS file selected: {filename}")
            
    def add_plan(self):
        plan_name = self.plan_name_entry.get().strip()
        plan_suffix = self.plan_suffix_entry.get().strip()
        geom_suffix = self.geom_suffix_entry.get().strip()
        flow_suffix = self.flow_suffix_entry.get().strip()
        other_suffixes = self.other_suffixes_entry.get().strip()
        
        if not plan_name or not plan_suffix:
            messagebox.showwarning("Input Error", "Plan Name and Plan Suffix are required")
            return
            
        # Validate suffixes are numeric
        if not plan_suffix.isdigit():
            messagebox.showwarning("Input Error", "Plan Suffix should be a number (e.g., 03)")
            return
            
        # Create suffix dictionary
        suffix_dict = {
            'plan': plan_suffix,
            'geom': geom_suffix if geom_suffix else plan_suffix,  # Default to plan suffix if not specified
            'flow': flow_suffix if flow_suffix else plan_suffix,  # Default to plan suffix if not specified
            'other': other_suffixes
        }
        
        # Add to treeview
        self.plan_tree.insert('', tk.END, values=(
            plan_name, 
            plan_suffix, 
            geom_suffix if geom_suffix else plan_suffix,
            flow_suffix if flow_suffix else plan_suffix,
            other_suffixes
        ))
        
        # Clear entries
        self.plan_name_entry.delete(0, tk.END)
        self.plan_suffix_entry.delete(0, tk.END)
        self.geom_suffix_entry.delete(0, tk.END)
        self.flow_suffix_entry.delete(0, tk.END)
        self.other_suffixes_entry.delete(0, tk.END)
        
        self.log(f"Added plan: {plan_name} (Plan:{plan_suffix}, Geom:{geom_suffix or plan_suffix}, Flow:{flow_suffix or plan_suffix})")
        
    def remove_plan(self):
        selected = self.plan_tree.selection()
        if selected:
            values = self.plan_tree.item(selected[0])['values']
            self.plan_tree.delete(selected[0])
            self.log(f"Removed plan: {values[0]}")
            
    def clear_plans(self):
        for item in self.plan_tree.get_children():
            self.plan_tree.delete(item)
        self.log("Cleared all plans")
        
    def log(self, message):
        """Add message to log queue"""
        self.log_queue.put(message)
        
    def update_status(self, message):
        """Update status bar"""
        self.status_var.set(message)
        self.root.update()
        
    def execute_simulations(self):
        """Run the HECRAS simulations"""
        # Validate inputs
        if not self.project_path.get():
            messagebox.showerror("Error", "Please select a project file")
            return
            
        if not os.path.exists(self.project_path.get()):
            messagebox.showerror("Error", "Project file does not exist")
            return
            
        plans = []
        for item in self.plan_tree.get_children():
            values = self.plan_tree.item(item)['values']
            plan_config = {
                'name': values[0],
                'plan_suffix': values[1],
                'geom_suffix': values[2],
                'flow_suffix': values[3],
                'other': values[4] if len(values) > 4 else ''
            }
            plans.append(plan_config)
            
        if not plans:
            messagebox.showerror("Error", "Please add at least one plan")
            return
            
        # Log the plans that will be run
        self.log("Plans to run:")
        for plan in plans:
            self.log(f"  - {plan['name']}: Plan=.p{plan['plan_suffix']}, Geom=.g{plan['geom_suffix']}, Flow=.u{plan['flow_suffix']}")
            
        # Disable execute button during execution
        self.execute_btn.config(state=tk.DISABLED)
        self.progress.start()
        
        # Clear log
        self.log_text.delete(1.0, tk.END)
        
        # Run in separate thread to prevent GUI freezing
        thread = threading.Thread(target=self.run_simulations_thread, 
                                 args=(plans,))
        thread.daemon = True
        thread.start()
        
    def run_simulations_thread(self, plans):
        """Run simulations in a separate thread"""
        try:
            self.log("="*60)
            self.log("STARTING HECRAS SIMULATIONS")
            self.log("="*60)
            
            # Get input values
            original_project_path = self.project_path.get()
            original_dss_path = self.dss_path.get() if self.dss_path.get() else None
            main_project_dir = os.path.dirname(original_project_path)
            
            # Check HECRAS installation
            self.update_status("Checking HECRAS installation...")
            if not self.check_hecras_installed():
                self.log("ERROR: HECRAS is not properly installed or registered.")
                return
            
            # Prepare temporary directories for each plan
            self.update_status("Preparing temporary directories...")
            temp_paths = []
            plan_configs = []
            
            for plan in plans:
                self.log(f"\nPreparing {plan['name']}...")
                temp_project, temp_dir = self.copy_project_to_temp(
                    original_project_path, 
                    original_dss_path, 
                    plan
                )
                temp_paths.append((temp_project, plan, temp_dir))
                plan_configs.append((temp_project, plan['name']))
            
            # Run simulations
            if self.run_parallel.get():
                # Run in parallel using multiprocessing
                self.run_parallel_simulations(plan_configs)
            else:
                # Run sequentially
                for temp_project, plan_name in plan_configs:
                    self.run_single_simulation(temp_project, plan_name)
            
            self.log("\nAll simulations completed.")
            
            # Copy all results back
            self.update_status("Copying results back to main project...")
            for temp_project, plan, temp_dir in temp_paths:
                self.copy_results_to_main_project(temp_project, main_project_dir, plan)
            
            self.log("\nAll results copied to main project folder.")
            self.log("Open RAS Mapper and refresh to see new results.")
            
            # Cleanup
            if self.cleanup_temp.get():
                self.log("\nCleaning up temporary files...")
                self.cleanup_temp_dirs(temp_paths)
                    
        except Exception as e:
            self.log(f"Error during simulation: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Re-enable execute button
            self.root.after(0, self.enable_execute_button)
            
    def run_parallel_simulations(self, plan_configs):
        """Run simulations in parallel using multiprocessing"""
        processes = []
        
        for temp_project, plan_name in plan_configs:
            self.log(f"Starting {plan_name} in parallel...")
            p = Process(target=run_hecras_plan_process, 
                       args=(temp_project, plan_name))
            p.start()
            processes.append(p)
        
        # Wait for all to complete
        for p in processes:
            p.join()
            
    def run_single_simulation(self, temp_project, plan_name):
        """Run a single simulation"""
        self.log(f"Running {plan_name}...")
        run_hecras_plan_process(temp_project, plan_name)
            
    def enable_execute_button(self):
        """Re-enable the execute button"""
        self.execute_btn.config(state=tk.NORMAL)
        self.progress.stop()
        self.update_status("Ready")
        self.log("="*60)
        self.log("SIMULATIONS COMPLETED")
        self.log("="*60)
        messagebox.showinfo("Complete", "All simulations completed successfully!")
            
    def check_hecras_installed(self):
        """Check if HECRAS is installed and accessible"""
        try:
            pythoncom.CoInitialize()
            ras = win32com.client.Dispatch("RAS66.HECRASController")
            ras.QuitRas()
            pythoncom.CoUninitialize()
            self.log("HECRAS installation verified")
            return True
        except Exception as e:
            self.log(f"HECRAS check failed: {e}")
            return False
            
    def copy_project_to_temp(self, original_project_path, original_dss_path, plan):
        """Copy project to temporary directory, copying ALL necessary files"""
        original_folder = os.path.dirname(original_project_path)
        temp_dir = tempfile.mkdtemp(prefix="HECRAS_")
        self.log(f"Created temporary folder: {temp_dir}")
        
        project_name = os.path.basename(original_project_path)
        project_basename = os.path.splitext(project_name)[0]  # PRtest1 without .prj
        
        # Copy project file
        shutil.copy2(original_project_path, os.path.join(temp_dir, project_name))
        self.log(f"  Copied project file: {project_name}")
        
        # Get all files in the original folder
        all_files = os.listdir(original_folder)
        
        # Define all possible HECRAS file extensions
        all_extensions = [
            'p', 'g', 'u', 'b', 'x', 'c', 'f', 'v', 's', 't', 'i', 'q', 
            'bco', 'ic.o', 'dss', 'hdf'
        ]
        
        # Also look for files with any numeric suffixes
        files_copied = 0
        copied_files_list = []
        
        for file in all_files:
            file_lower = file.lower()
            file_basename = os.path.splitext(file)[0]
            
            # Skip if it's the project file (already copied)
            if file == project_name:
                continue
                
            # Check if this file belongs to our project
            if file_basename == project_basename:
                # This file has the same basename as the project
                dst = os.path.join(temp_dir, file)
                shutil.copy2(os.path.join(original_folder, file), dst)
                copied_files_list.append(file)
                files_copied += 1
                continue
                
            # Also check for files that might have the project name with suffixes
            # This handles cases like PRtest1.p03, PRtest1.g01, etc.
            for ext in all_extensions:
                pattern = f"{project_basename}.{ext}"
                if file_lower.startswith(pattern.lower()) or file_lower == pattern.lower():
                    dst = os.path.join(temp_dir, file)
                    shutil.copy2(os.path.join(original_folder, file), dst)
                    copied_files_list.append(file)
                    files_copied += 1
                    break
        
        # Log copied files
        if copied_files_list:
            self.log(f"  Copied {files_copied} additional files:")
            for f in sorted(copied_files_list)[:10]:  # Show first 10
                self.log(f"    - {f}")
            if len(copied_files_list) > 10:
                self.log(f"    ... and {len(copied_files_list)-10} more")
        else:
            self.log(f"  WARNING: No additional files copied for plan {plan['name']}")
        
        # Update DSS path in U files specifically for this plan's flow suffix
        if original_dss_path and plan['flow_suffix']:
            self.update_dss_path_in_u_files(temp_dir, original_dss_path, plan['flow_suffix'])
        
        return os.path.join(temp_dir, project_name), temp_dir
        
    def update_dss_path_in_u_files(self, temp_dir, original_dss_path, flow_suffix):
        """Update DSS path in U files"""
        normalized_path = os.path.normpath(original_dss_path)
        updated = False
        
        for file in os.listdir(temp_dir):
            # Look for any .u files, not just those with specific suffix
            if file.lower().endswith(f".u{flow_suffix}".lower()) or file.lower().endswith('.u'):
                u_file_path = os.path.join(temp_dir, file)
                
                try:
                    with open(u_file_path, 'r') as f:
                        lines = f.readlines()
                    
                    new_lines = []
                    found = False
                    for line in lines:
                        if "DSS File=" in line:
                            found = True
                            new_lines.append(f"DSS File={normalized_path}\n")
                            self.log(f"  Updated DSS path in {file}")
                            updated = True
                        else:
                            new_lines.append(line)
                    
                    if not found:
                        new_lines.insert(0, f"DSS File={normalized_path}\n")
                        self.log(f"  Added DSS path to {file}")
                        updated = True
                    
                    with open(u_file_path, 'w') as f:
                        f.writelines(new_lines)
                except Exception as e:
                    self.log(f"  Error updating {file}: {e}")
        
        if not updated:
            self.log(f"  No .u files found to update DSS path")
                    
    def copy_results_to_main_project(self, temp_project_path, main_project_dir, plan):
        """Copy results back to main project directory"""
        temp_dir = os.path.dirname(temp_project_path)
        copied_files = []
        
        for file in os.listdir(temp_dir):
            src = os.path.join(temp_dir, file)
            dst = os.path.join(main_project_dir, file)
            try:
                # Only copy if it doesn't exist or is newer
                if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                    shutil.copy2(src, dst)
                    copied_files.append(file)
            except Exception as e:
                self.log(f"Error copying {file}: {e}")
        
        if copied_files:
            self.log(f"Copied {len(copied_files)} result files for {plan['name']}")
        else:
            self.log(f"Warning: No result files copied for {plan['name']}")
                    
    def cleanup_temp_dirs(self, temp_paths):
        """Clean up temporary directories"""
        for temp_project, plan, temp_dir in temp_paths:
            try:
                shutil.rmtree(temp_dir)
                self.log(f"Cleaned up: {temp_dir}")
            except Exception as e:
                self.log(f"Error cleaning up {temp_dir}: {e}")

# Standalone function for multiprocessing
def run_hecras_plan_process(project_path, plan_name):
    """Run a single HECRAS plan in a separate process"""
    try:
        pythoncom.CoInitialize()
        ras = win32com.client.Dispatch("RAS66.HECRASController")
        ras.ShowRas()
        
        print(f"[{plan_name}] Opening project: {os.path.basename(project_path)}")
        ras.Project_Open(project_path)
        
        # Give HECRAS time to load the project
        time.sleep(3)
        
        print(f"[{plan_name}] Setting current plan to: {plan_name}")
        ras.Plan_SetCurrent(plan_name)
        
        # Give HECRAS time to set the plan
        time.sleep(2)
        
        print(f"[{plan_name}] Starting computation...")
        ras.Compute_CurrentPlan()
        
        # Wait for computation to complete
        while ras.Compute_Complete() == 0:
            print(f"[{plan_name}] Computing...")
            time.sleep(5)
        
        print(f"[{plan_name}] Computation completed successfully!")
        
        # Close project
        ras.Project_Close()
        ras.QuitRas()
        
    except Exception as e:
        print(f"[{plan_name}] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        pythoncom.CoUninitialize()

def main():
    root = tk.Tk()
    app = HECRASParallelRunnerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    # Required for multiprocessing on Windows
    multiprocessing.freeze_support()
    main()