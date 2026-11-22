# Gunicorn settings for the Docker image. Gunicorn reads this file automatically from the working directory.
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Two worker processes with four threads each.
workers = 2
threads = 4
# Leaves room for Snap-a-Flyer, which waits up to 25 s for the vision model.
timeout = 60

# Request and error logs go to the container's output, which App Service shows in Log stream.
accesslog = '-'
errorlog = '-'
# The default format plus how long each request took, e.g. ... 200 84243 412ms.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(f)s" "%(a)s"'
