"""BCM2837 DT/sysfs fixtures; link resolution mocked for Windows portability."""
import contextlib
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_oled import ROOT
import pikvm_gpio as gpio


def cells(*values):
    return b''.join(value.to_bytes(4,'big') for value in values)


@contextlib.contextmanager
def platform_fixture(resource=False, parent_cells=1):
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);dt=root/'dt';sysroot=root/'sys';soc=dt/'soc'
        gpio_node=soc/'gpio@7e200000';mem_node=soc/'gpiomem'
        gpio_node.mkdir(parents=True);mem_node.mkdir()
        (dt/'compatible').write_bytes(b'raspberrypi,model-zero-2-w\0brcm,bcm2837\0')
        (dt/'#address-cells').write_bytes(cells(parent_cells))
        (soc/'compatible').write_bytes(b'simple-bus\0')
        (soc/'#address-cells').write_bytes(cells(1));(soc/'#size-cells').write_bytes(cells(1))
        ranges=[0x7e000000]+([0] if parent_cells==2 else [])+[0x3f000000,0x1000000]
        (soc/'ranges').write_bytes(cells(*ranges))
        (gpio_node/'compatible').write_bytes(b'brcm,bcm2835-gpio\0')
        (gpio_node/'reg').write_bytes(cells(0x7e200000,0xb4))
        (mem_node/'compatible').write_bytes(b'brcm,bcm2835-gpiomem\0')
        (mem_node/'reg').write_bytes(cells(0x7e200000,0x1000))
        platform=sysroot/'devices/platform/soc/3f200000.gpiomem';platform.mkdir(parents=True)
        driver=sysroot/'bus/platform/drivers/rpi-gpiomem';driver.mkdir(parents=True)
        entry=driver/'3f200000.gpiomem';entry.mkdir()
        class_device=sysroot/'devices/virtual/gpiomem/gpiomem';class_device.mkdir(parents=True)
        (class_device/'dev').write_text('238:0')
        (class_device/'uevent').write_text('MAJOR=238\nMINOR=0\nDEVNAME=gpiomem\n')
        if resource:(platform/'resource').write_text('0x3f200000 0x3f200fff 0x200\n')
        links={entry:platform,platform/'driver':driver,platform/'of_node':mem_node,
               sysroot/'class/gpiomem/gpiomem':class_device,
               sysroot/'dev/char/238:0':class_device}
        original=Path.resolve
        def resolve(path,*args,**kwargs):
            if path in links:return links[path]
            return original(path,*args,**kwargs)
        with patch.object(gpio.Path,'resolve',autospec=True,side_effect=resolve), \
             patch.object(gpio.Path,'lstat',return_value=Mock(st_mode=stat.S_IFCHR,st_rdev=0)), \
             patch.object(gpio.os,'major',return_value=238,create=True),patch.object(gpio.os,'minor',return_value=0,create=True):
            yield {'dt':dt,'soc':soc,'sys':sysroot,'platform':platform,'driver':driver,
                   'entry':entry,'mem':mem_node,'gpio':gpio_node,'class':class_device,'links':links}


def validate(fixture):
    return gpio.validate_platform(fixture['dt']/'compatible',fixture['sys'])


class PlatformTests(unittest.TestCase):
    def test_missing_resource_uses_actual_reg_ranges_and_links(self):
        for parent_cells in (1,2):
            with self.subTest(parent_cells=parent_cells),platform_fixture(parent_cells=parent_cells) as f:
                result=validate(f)
                self.assertFalse(result['resource_present']);self.assertEqual(result['devno'],'238:0')
                self.assertEqual(result['gpio_region']['bus'],0x7e200000)
                self.assertEqual(result['gpio_region']['physical'],0x3f200000)
                self.assertEqual(result['gpio_region']['size'],0xb4)
                self.assertEqual(result['gpiomem_region']['size'],0x1000)
                (f['mem']/'reg').write_bytes(cells(0x7e200000,0xb4))
                self.assertEqual(validate(f)['gpiomem_region']['size'],0xb4)

    def test_present_resource_must_agree_with_dt(self):
        with platform_fixture(resource=True) as f:
            self.assertTrue(validate(f)['resource_present'])
            for row in ('0xfe200000 0xfe200fff 0x200\n','0x3f200000 0x3f200fff 0x100\n'):
                (f['platform']/'resource').write_text(row)
                with self.assertRaisesRegex(gpio.Unavailable,'contradicts'):validate(f)

    def test_bad_ranges_are_never_replaced_by_a_hardcoded_address(self):
        variants=[cells(0x7e000000,0xfe000000,0x1000000),
                  cells(0x7e000000,0x3f000000,0x200034),
                  cells(0x7e000000,0x3f000000,0x1000000)*2,
                  b'',b'\x00\x01']
        for ranges in variants:
            for resource in (False,True):
                with self.subTest(ranges=ranges.hex(),resource=resource),platform_fixture(resource=resource) as f:
                    (f['soc']/'ranges').write_bytes(ranges)
                    with self.assertRaises(gpio.Unavailable):validate(f)

    def test_registers_compatibles_and_cell_counts_fail_closed(self):
        changes=[('gpio','reg',cells(0x7e210000,0xb4)),('gpio','reg',cells(0x7e200000,0x10)),
                 ('mem','reg',cells(0x7e210000,0x1000)),('mem','reg',cells(0x7e200000,0x2000)),
                 ('mem','reg',cells(0x7e200000,0x1000)*2),
                 ('mem','compatible',b'raspberrypi,gpiomem\0'),
                 ('gpio','compatible',b'brcm,bcm2711-gpio\0'),
                 ('soc','#address-cells',cells(3)),('gpio','status',b'disabled\0')]
        for node,name,value in changes:
            with self.subTest(node=node,name=name,value=value),platform_fixture() as f:
                (f[node]/name).write_bytes(value)
                with self.assertRaises(gpio.Unavailable):validate(f)

    def test_incoherent_sysfs_identities_and_binding_links_are_rejected(self):
        for change in ('devno','charlink','driver','of_node','entry','uevent'):
            with self.subTest(change=change),platform_fixture() as f:
                if change=='devno':(f['class']/'dev').write_text('239:0')
                elif change=='charlink':f['links'][f['sys']/'dev/char/238:0']=f['platform']
                elif change=='driver':f['links'][f['platform']/'driver']=f['sys']/'wrong-driver'
                elif change=='of_node':f['links'][f['platform']/'of_node']=f['gpio']
                elif change=='entry':f['links'][f['entry']]=f['sys']/'devices/platform/soc/fe200000.gpiomem'
                else:(f['class']/'uevent').write_text('MAJOR=238\nMINOR=0\nDEVNAME=other\n')
                with self.assertRaises(gpio.Unavailable):validate(f)

    def test_missing_translation_and_ambiguous_drivers_do_not_authorize_mapping(self):
        with platform_fixture() as f:
            (f['soc']/'ranges').unlink()
            with self.assertRaises(OSError):validate(f)
        with platform_fixture() as f:
            second=f['sys']/'bus/platform/drivers/gpiomem-bcm2835/3f200000.gpiomem';second.mkdir(parents=True)
            f['links'][second]=f['platform']
            with self.assertRaises(gpio.Unavailable):validate(f)
