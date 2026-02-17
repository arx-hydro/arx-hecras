# arx-hecras — Architecture

How the HEC-RAS Parallel Runner works, from user input to simulation results.

## 1. Overall System Flow

The tool has two entry points (GUI and CLI) that share the same execution pipeline.

```mermaid
flowchart TB
    subgraph Entry["Entry Points"]
        GUI["hecras_gui_runner.py\nTkinter GUI"]
        CLI["run_hecras_parallel.py\nHeadless CLI"]
    end

    subgraph Pipeline["Shared Execution Pipeline"]
        CHECK["Check HEC-RAS\nInstallation"]
        PREP["Prepare Temp\nDirectories"]
        RUN["Launch Parallel\nProcesses"]
        WAIT["Wait for All\nto Complete"]
        HARVEST["Copy Results\nBack"]
        CLEAN["Cleanup Temp\nDirectories"]
    end

    GUI -->|"threading.Thread"| CHECK
    CLI --> CHECK
    CHECK -->|"COM: Dispatch + QuitRas"| PREP
    PREP --> RUN
    RUN --> WAIT
    WAIT --> HARVEST
    HARVEST --> CLEAN
```

## 2. Temp Directory Isolation

HEC-RAS locks project files during computation. Each plan runs against its own copy in a temp directory, preventing file access conflicts.

```mermaid
flowchart LR
    subgraph Original["Original Project Folder"]
        PRJ["PRtest1.prj"]
        G01["PRtest1.g01"]
        P03["PRtest1.p03"]
        P04["PRtest1.p04"]
        U03["PRtest1.u03"]
        U04["PRtest1.u04"]
        DSS["100yCC_2024.dss"]
        TERRAIN["Terrain/"]
    end

    PRJ -->|"shutil.copy2\n+ copytree"| T1
    PRJ -->|"shutil.copy2\n+ copytree"| T2

    subgraph T1["HECRAS_xxxx (temp 1)"]
        T1PRJ["PRtest1.prj"]
        T1P["PRtest1.p03"]
        T1U["PRtest1.u03\nDSS path patched"]
    end

    subgraph T2["HECRAS_yyyy (temp 2)"]
        T2PRJ["PRtest1.prj"]
        T2P["PRtest1.p04"]
        T2U["PRtest1.u04\nDSS path patched"]
    end

    T1 -->|"Results copied back\nby extension + suffix"| Original
    T2 -->|"Results copied back\nby extension + suffix"| Original
```

## 3. DSS Path Patching

When a plan references an external DSS file (e.g. HEC-HMS hydrograph input), the path in `.u##` files must point back to the original location since the temp directory is elsewhere on disk.

```mermaid
flowchart TD
    COPY["All files copied\nto temp dir"] --> SCAN["Scan temp dir for\n.u01 .u02 .u03 .u04"]
    SCAN --> READ["Read .u file line by line"]
    READ --> FOUND{"Line contains\n'DSS File='?"}
    FOUND -->|Yes| REPLACE["Replace with\noriginal absolute path"]
    FOUND -->|No| KEEP["Keep line as-is"]
    REPLACE --> WRITE["Write modified\nfile back"]
    KEEP --> WRITE
```

## 4. Process Architecture

The GUI runs simulation logic in a background thread. Each plan gets its own child process with an independent COM connection to a separate HEC-RAS instance.

```mermaid
flowchart TB
    subgraph MainProcess["Main Process"]
        subgraph UIThread["UI Thread (tkinter)"]
            WIDGETS["GUI Widgets"]
            QUEUE_READ["queue.Queue\nreader\n100ms polling"]
            LOG["Log Panel"]
            QUEUE_READ --> LOG
        end
        subgraph WorkerThread["Worker Thread"]
            PREP2["Prepare temp dirs"]
            LAUNCH["Launch processes"]
            JOIN["Join processes"]
            COPY_BACK["Copy results back"]
            PREP2 --> LAUNCH --> JOIN --> COPY_BACK
        end
    end

    subgraph Child1["Child Process 1"]
        COM1["pythoncom.CoInitialize()"]
        RAS1["RAS66.HECRASController"]
        HEC1["HEC-RAS 6.6 Instance"]
        COM1 --> RAS1 --> HEC1
    end

    subgraph Child2["Child Process 2"]
        COM2["pythoncom.CoInitialize()"]
        RAS2["RAS66.HECRASController"]
        HEC2["HEC-RAS 6.6 Instance"]
        COM2 --> RAS2 --> HEC2
    end

    LAUNCH -->|"multiprocessing.Process"| Child1
    LAUNCH -->|"multiprocessing.Process"| Child2

    WorkerThread -.->|"log_queue.put()"| QUEUE_READ
```

## 5. COM Automation Sequence

Each child process follows this sequence to drive a HEC-RAS instance. The entire lifecycle happens inside a single `multiprocessing.Process`.

```mermaid
sequenceDiagram
    participant P as Child Process
    participant COM as pythoncom
    participant RAS as HECRASController
    participant HEC as HEC-RAS 6.6

    P->>COM: CoInitialize()
    P->>RAS: Dispatch("RAS66.HECRASController")
    P->>RAS: ShowRas()
    RAS->>HEC: Launch GUI window

    P->>RAS: Project_Open(temp_path)
    RAS->>HEC: Load project files
    Note over P: sleep(3)

    P->>RAS: Plan_SetCurrent(plan_name)
    Note over P: sleep(2)

    P->>RAS: Compute_CurrentPlan()
    RAS->>HEC: Start simulation

    loop Every 5 seconds
        P->>RAS: Compute_Complete()
        RAS-->>P: 0 (still running)
    end

    RAS-->>P: 1 (complete)
    P->>RAS: Project_Close()
    P->>RAS: QuitRas()
    RAS->>HEC: Close GUI window
    P->>COM: CoUninitialize()
```

## 6. Result Harvesting

After all processes complete, result files are copied from each temp directory back to the original project folder, matched by extension and plan suffix number.

```mermaid
flowchart LR
    subgraph Temp["Temp Directory"]
        ALL["All files in\ntemp dir"]
    end

    ALL --> MATCH{"File ends with\n.ext + suffix?"}

    MATCH -->|".p03"| COPY
    MATCH -->|".u03"| COPY
    MATCH -->|".g03"| COPY
    MATCH -->|".b03"| COPY
    MATCH -->|".bco03"| COPY
    MATCH -->|".dss03"| COPY
    MATCH -->|".ic.o03"| COPY
    MATCH -->|".x03"| COPY
    MATCH -->|".p03.hdf"| COPY
    MATCH -->|"other"| SKIP["Skip"]

    subgraph Exts["Matched Extensions"]
        COPY["shutil.copy2\nto original dir"]
    end
```

## 7. GUI vs CLI Differences

```mermaid
flowchart TB
    subgraph gui["hecras_gui_runner.py"]
        G_INPUT["File browser dialogs\nfor .prj and .dss"]
        G_PLANS["Plan tree widget\nadd/remove plans"]
        G_OPTS["Checkboxes:\nparallel, cleanup"]
        G_THREAD["Background thread\nfor execution"]
        G_LOG["Scrolling log panel\nwith timestamps"]
        G_COPY["Copies only newer\nfiles back"]

        G_INPUT --> G_PLANS --> G_OPTS --> G_THREAD --> G_LOG
    end

    subgraph cli["run_hecras_parallel.py"]
        C_INPUT["Hardcoded paths\nin run_simulations()"]
        C_PLANS["Hardcoded plan list\nwith name, dss, suffix"]
        C_OPTS["Always parallel\nalways cleanup"]
        C_DIRECT["Direct execution\nin main process"]
        C_LOG["print to console"]
        C_COPY["Copies by extension\n+ suffix matching"]

        C_INPUT --> C_PLANS --> C_OPTS --> C_DIRECT --> C_LOG
    end
```

## 8. HEC-RAS Project File Structure

How the test project components reference each other.

```mermaid
graph TD
    PRJ["PRtest1.prj\nProject File"]

    PRJ -->|"Geom File=g01"| G01["PRtest1.g01\nGeometry: geoBR\n2D, 1095 mesh cells"]

    PRJ -->|"Plan File=p01"| P01["PRtest1.p01\nplan01"]
    PRJ -->|"Plan File=p02"| P02["PRtest1.p02\nplan02"]
    PRJ -->|"Plan File=p03"| P03["PRtest1.p03\nplan03"]
    PRJ -->|"Plan File=p04"| P04["PRtest1.p04\nplan04"]

    PRJ -->|"Unsteady File=u01"| U01["PRtest1.u01\nunsteady01\npeak ~5 m³/s"]
    PRJ -->|"Unsteady File=u02"| U02["PRtest1.u02\nunsteady02\npeak ~10 m³/s"]
    PRJ -->|"Unsteady File=u03"| U03["PRtest1.u03\nunsteady03\npeak ~10 m³/s"]
    PRJ -->|"Unsteady File=u04"| U04["PRtest1.u04\nunsteady04\npeak ~20 m³/s"]

    P01 -->|"Geom File=g01"| G01
    P02 -->|"Geom File=g01"| G01
    P03 -->|"Geom File=g01"| G01
    P04 -->|"Geom File=g01"| G01

    P01 -->|"Flow File=u01"| U01
    P02 -->|"Flow File=u02"| U02
    P03 -->|"Flow File=u03"| U03
    P04 -->|"Flow File=u04"| U04

    G01 -->|"references"| TERRAIN["Terrain/\nexisting_02.hdf"]
    G01 -->|"references"| LAND["Land Classification/\nLandCover.tif"]

    PRJ -->|"DSS File="| DSS["100yCC_2024.dss\nHEC-HMS input"]

    style PRJ fill:#4a90d9,color:white
    style P01 fill:#5ba55b,color:white
    style P02 fill:#5ba55b,color:white
    style P03 fill:#5ba55b,color:white
    style P04 fill:#5ba55b,color:white
    style G01 fill:#d4a44a,color:white
    style U01 fill:#d97a4a,color:white
    style U02 fill:#d97a4a,color:white
    style U03 fill:#d97a4a,color:white
    style U04 fill:#d97a4a,color:white
    style TERRAIN fill:#888,color:white
    style LAND fill:#888,color:white
    style DSS fill:#9b59b6,color:white
```
