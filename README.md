# miband3-resource-hacker
A Tool to pack and repack mi-band 3 resource files

## Disclaimer

Using this tool may brick your mi band; I built this on a sunday afternoon for fun, it works for me but, I take no responsibility if your device breaks etc.

## How to & Usage

Install Pillow if you don't already have it on your system:

	$ pip install Pillow

Get the firmware and resource files from a Mi Fit APK and extract them.

Put the `Mili_wuhan.res` next to the `miband_res_hack.py` and unpack the files like so:

	$ miband_res_hack.py unpack Mili_wuhan.res

this will create a folder `unpacked` you can edit the pngs in the folder
using GIMP. Make sure not to change anything about the color palettes (only use the
colors that are already available in the pngs)!

After changing stuff you can repack the resfile:

	$ miband_res_hack.py repack Mili_wuhan.res

This will create a new res file `Mili_wuhan.new.res` next to the old one.

Use [GadgetBridge](https://gadgetbridge.org/) to upload the res file to your mi-band.

