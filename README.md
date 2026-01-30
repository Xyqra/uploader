## Uploader

a really simple uploader created in 5min with help from AI lol

### how2:

- download files:
```bash
git clone https://github.com/Xyqra/uploader.git
cd uploader
```

- install python packages
```bash
pip install -r requirements.txt
```

- config the python file (set these values)
  -  `API_KEY` to some string u want to use as you upload api key
  -  `UPLOAD_FOLDER` to folder where the files should be stored
  -  `LOGS_FOLDER` to where logs should be stored, kept indefinitely
  -  `BASE_URL` to your external url
  -  `TZ` edit to your timezone for logs

- run it
just execute app.py with python

listens on `0.0.0.0:6942` (u can change port at the bottom of the file)

### api:

#### upload:

POST `/api/upload` upload a file
header `X-API-Key` with the value of `API_KEY` in config
the file in `multipart/form-data` under field name `file`

returns
- 200:
  - json: `{"url": "<BASE_URL>/<hash>"}`
- 400:
  - no file part
    - json: `{"error":"No file provided"}`
  - empty filename
    - json: `{"error":"No file selected"}` 
- 401:
  - wrong/missing API key
    - json: `{"error":"Unauthorized"}`
   
#### get/download:

GET `/<file_hash>` get an uploaded file

GET `/<file_hash>.<extension>` (extension is optional)

returns:
- `200`:
  - raw file response
- `404`:
  - json: `{"error":"File not found"}`
