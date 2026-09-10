# ReEzSynth Windows GUI

A Windows graphical front end for preparing and running keyframe-based
video stylization with Ezsynth and EbSynth.

ReEzSynth aims to make the workflow easier to manage: select your source
image sequence and styled keyframes, configure frame ranges, queue renders,
and monitor progress without manually preparing each rendering job.

## Project goals

- Make keyframe-based rendering more accessible through a Windows interface.
- Provide clear control over frame ranges and rendering options.
- Organize multiple render jobs into a manageable queue.
- Show useful progress, logs, and error messages.
- Reduce repeated startup overhead while keeping worker cleanup explicit.

Worker reuse is enabled by default for queued renders. Each job initializes
its own rendering engine, while the Python worker stays running between
jobs and exits when the queue finishes. An isolated-worker option is
available for troubleshooting memory growth or instability.

## Status

ReEzSynth is under active development. The interface and workflow may
change as rendering, queue management, and resource handling are refined.

## Credits and attribution

### EbSynth — Secret Weapons

[EbSynth](https://ebsynth.com/) is developed by **Secret Weapons**.
Its synthesis technology is a foundation of this workflow.

Website: **https://ebsynth.com/**

### Ezsynth — FuouM

[Ezsynth](https://github.com/FuouM/Ezsynth) is developed by **FuouM and
contributors**. It provides the Python rendering pipeline that this
front end builds upon.

GitHub: **https://github.com/FuouM/Ezsynth**

### ReEzSynth Windows GUI

ReEzSynth focuses on the Windows interface, job preparation, queue
management, and user experience around these existing tools. It does not
claim authorship of EbSynth or Ezsynth and is not an official release from
their developers.

Please retain the upstream license files and attribution notices when
redistributing this project.