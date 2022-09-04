# Root-Detector
Analysis tool for minirhizotron images

Screenshot:

<img src="images/screenshot.jpg" width="1000">


***

### Running from source

Tested with Python 3.7

```bash
#clone the repository including submodules
git clone --recursive https://github.com/alexander-g/Root-Detector.git
cd Root-Detector

#create new virtual environment and install requirements
python -m venv venv
source venv/bin/activate              #linux
#venv/Scripts/activate.bat                #windows
pip install -r requirements.txt

#download pretrained models
python fetch_pretrained_models.py

#run
python main.py

#in a browser, navigate to http://localhost:5000
#drag+drop images from images/sample_data and process
```

***

### Citation
Source code for publication (in review):
```
Peters, B. et al. "As good as but much more efficient and reproducible 
than human experts in detecting plant roots in minirhizotron images: 
The Convolutional Neural Network RootDetector" (2022)
```

Root tracking:
```
Alexander Gillert, Bo Peters, Uwe Freiherr von Lukas, Jürgen Kreyling and Gesche Blume-Werry. 
"Tracking Growth and Decay of Plant Roots in Minirhizotron Images." 
Proceedings of the IEEE/CVF Winter Conference on Applications of Computer Vision (WACV), 2023 (accepted)
```
