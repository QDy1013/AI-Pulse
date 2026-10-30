"""Behavior checks for the desktop redesign using synthetic metrics only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pulse.app import Pulse, format_model_names, parse_model_names
from pulse.collector import APPS, Request

class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=QApplication.instance() or QApplication([])

    def setUp(self):
        self.window=Pulse();self.window.timer.stop()
        now=time.time()
        data={a:{'requests':[Request(a,a,now,'test-model',output=100*(i+1),seconds=5)],'errors':0,'status':'测试来源'} for i,a in enumerate(APPS)}
        data['Codex']['requests'].append(Request('old','Codex',now-10*86400,'test-model',output=999))
        self.window.received(data);self.window.resize(1100,740);self.window.show()

    def tearDown(self):self.window.close()

    def test_filter_preserves_totals_and_pause_controls(self):
        self.assertEqual(sum(r.output for r in self.window.rows),1500)
        QTest.mouseClick(self.window.nav['WorkBuddy'],Qt.MouseButton.LeftButton)
        self.assertEqual(len(self.window.rows),1)
        self.assertEqual(self.window.rows[0].output,500)
        QTest.mouseClick(self.window.pause_button,Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.paused)
        QTest.mouseClick(self.window.nav['Codex'],Qt.MouseButton.LeftButton)
        QTest.mouseClick(self.window.period_buttons['全部记录'],Qt.MouseButton.LeftButton)
        self.assertEqual(sum(r.output for r in self.window.rows),1099)
        self.assertEqual(self.window.table.rowCount(),2)

    def test_high_dpi_capture_and_small_window_layout(self):
        self.window.resize(1000,680);self.application.processEvents()
        self.assertLessEqual(self.window.content.width(),self.window.width())
        pix=self.window.grab()
        self.assertEqual(pix.width(),round(self.window.width()*pix.devicePixelRatio()))
        self.assertGreater(self.window.cards[0].value.fontMetrics().height(),20)

    def test_unchanged_scan_keeps_selection_and_old_data_falls_back_to_all(self):
        self.window.table.selectRow(1)
        self.window.received(self.window.data)
        self.assertEqual(self.window.table.currentRow(),1)
        fresh=Pulse();fresh.timer.stop()
        old={a:{'requests':[],'errors':0,'status':'x'} for a in APPS}
        old['Codex']['requests']=[Request('o','Codex',time.time()-3*86400,'m',output=10)]
        fresh.received(old)
        self.assertEqual(fresh.period,'全部记录')
        self.assertEqual(len(fresh.rows),1)
        fresh.close()

    def test_model_name_table_round_trip(self):
        names=parse_model_names('1418 = B\n bad line \n1401 = Claude Opus 5.5\n= x\n')
        self.assertEqual(names,{'1418':'B','1401':'Claude Opus 5.5'})
        self.assertEqual(format_model_names(names),'1401 = Claude Opus 5.5\n1418 = B')

if __name__=='__main__':unittest.main()
