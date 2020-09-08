from threading import Thread, Lock
import time
import logging

log = logging.getLogger(__name__)

class Accounting(Thread):
    def __init__(self, jobQueue, refresh = 5):
        super().__init__(daemon=True)
        self._jobdoing = 0
        self._jobdone = 0
        self._totalJob = 0
        self._joberror = 0
        self.jobQueue = jobQueue
        self.lock = Lock()
        self.refreshTime = refresh
        self.close = False
        self.start()

    def increaseJobdoing(self):
        with self.lock:
            self._jobdoing += 1

    def decreaseJobdoing(self):
        with self.lock:
            self._jobdoing -= 1

    def JobComplete(self):
        with self.lock:
            self._jobdone += 1

    def JobFailed(self):
        with self.lock:
            self._joberror += 1

    def TotalJob(self):
        log.debug("queue size %d, jobdoing %d, jobdone %d, joberror %d" % (self.jobQueue.qsize(), self._jobdoing, self._jobdone, self._joberror))
        with self.lock:
            self._totalJob = self.jobQueue.qsize() + self._jobdoing + self._jobdone + self._joberror

    def update(self):
        self.TotalJob()
        s = "\n\n* Complete: %d/%d, %0.2f%%\n" % (self._jobdone, self._totalJob, float(self._jobdone/self._totalJob*100.0))
        s += "* Error: %d/%d\n" % (self._joberror, self._totalJob)
        log.info(s)

    def run(self):
        while self._jobdoing == 0 and not self.close:
            time.sleep(1)

        while not self.close:
            self.update()
            time.sleep(self.refreshTime)

    def shutdown(self):
        self.update()
        self.close = True
