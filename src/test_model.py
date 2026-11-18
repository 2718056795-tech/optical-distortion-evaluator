from pathlib import Path
import unittest
import numpy as np
from engine import Curve,fit_curve,parse_input,UnitChoiceRequired
from model import Collection,Dataset,distortion_grade,distance_name,fit_grade,turning_points,turning_grade

SAMPLE=Path(__file__).resolve().parent.parent/'examples/畸变样例.txt'


class ModelTests(unittest.TestCase):
    def test_declared_distortion_units_and_file_paste_agree(self):
        plain = 'Angle  Distortion\n0  0\n10  0.05\n20  0.24\n30  0.72'
        for decl, maximum in [('畸变单位是百分比。', .72), ('Distortion is expressed as percentage.', .72),
                              ('Units of distortion are fractions.', 72.0)]:
            data = decl + '\n' + plain
            model = Collection()
            a = model.add_bytes(data.encode('utf-8'), 'case.txt')[0]
            b = model.add_text(data, 'case')[0]
            self.assertAlmostEqual(a.row_result()['dmax'], maximum)
            self.assertAlmostEqual(b.row_result()['dmax'], maximum)
        for header, maximum in [('Angle Distortion (fraction)',72.), ('Angle  Distortion (%)',.72)]:
            data = plain.replace('Angle  Distortion', header)
            self.assertAlmostEqual(Collection().add_text(data,'case')[0].row_result()['dmax'],maximum)

    def test_unresolved_units_cancel_without_adding_and_override_only_matters_for_that_block(self):
        clear = 'Wavelength: 440 nm\nAngle  Distortion (%)\n0  0\n10  .2\n20  .72'
        for header, conflict in [('Angle  Distortion', False), ('畸变单位是小数比例\nAngle  Distortion (%)', True)]:
            text = clear+'\nWavelength: 460 nm\n'+header+'\n0  0\n10  .002\n20  .0072'
            model = Collection()
            with self.assertRaises(UnitChoiceRequired) as issue:
                model.add_text(text, 'case')
            self.assertEqual(model.items, [])
            self.assertEqual(issue.exception.kind, 'distortion')
            self.assertEqual(issue.exception.conflict, conflict)
            dataset = model.add_text(text, 'case', unit_choices={issue.exception.key: 'fraction'})[0]
            self.assertEqual(dataset.own_waves(), ['0.44 μm','0.46 μm'])
            for wave in dataset.own_waves():
                self.assertAlmostEqual(dataset.result(wave)['dmax'], .72)

    def test_wavelength_units_and_missing_unit(self):
        data='Wavelength: {}\nAngle  Distortion (%)\n0  0\n10  .2\n20  .72'
        c=Collection()
        for wave in ('440 nm','0.44 um','0.440 µm','0.440000 μm'):
            c.add_text(data.format(wave), 'case')
        self.assertEqual(c.waves(), ['0.44 μm'])
        self.assertEqual(len(c.visible_results('0.44 μm')),4)
        with self.assertRaises(UnitChoiceRequired) as issue:
            c.add_text(data.format('440'),'case')
        self.assertEqual(issue.exception.kind, 'wavelength')
        self.assertEqual(len(c.items),4)
        c.add_text(data.format('440'),'case',unit_choices={issue.exception.key:'nm'})
        self.assertEqual(len(c.visible_results('0.44 μm')),5)
        text=data.format('440')+'\n'+data.format('0.46')
        units={issue.exception.key:'nm'}
        with self.assertRaises(UnitChoiceRequired) as second:
            c.add_text(text,'mixed',unit_choices=units)
        self.assertNotEqual(second.exception.key,issue.exception.key)
        units[second.exception.key]='μm'
        pair=c.add_text(text,'mixed',unit_choices=units)[0]
        self.assertEqual(pair.own_waves(), ['0.44 μm','0.46 μm'])

    def test_turning_color_boundaries(self):
        for count,key in [(0,'green'),(1,'green'),(2,'yellow'),(3,'red'),(4,'red')]:
            self.assertEqual(turning_grade(count)[0],key)
        self.assertEqual(distortion_grade(.2)[0],'green')
        self.assertEqual(turning_grade(2)[0],'yellow')

    def test_distortion_color_boundaries(self):
        for value,expected in [(0,'green'),(.49999,'green'),(.5,'green'),(.500001,'yellow'),(1,'yellow'),(1.000001,'red')]:
            self.assertEqual(distortion_grade(value)[0],expected)

    def test_file_and_paste_same_data(self):
        c=Collection();a=c.add_bytes(SAMPLE.read_bytes(),'300mm.txt')[0]
        b=c.add_text(SAMPLE.read_text(encoding='utf-16'),'600 mm')[0]
        self.assertEqual(c.waves(),['0.44 μm','0.46 μm','0.48 μm'])
        self.assertEqual(a.name,'300 mm');self.assertEqual(b.name,'600 mm')
        for w in c.waves():
            self.assertEqual(a.result(w)['n'],101)
            self.assertEqual(a.result(w)['unit'],'percent')
            self.assertAlmostEqual(a.result(w)['max_error'],b.result(w)['max_error'])
        self.assertEqual(len(c.visible_results('0.46 μm')),2)

    def test_multi_file_visibility_and_wavelength(self):
        c=Collection();a=c.add_bytes(SAMPLE.read_bytes(),'300mm.txt')[0]
        c.add_text('归一化半径  畸变(%)\n0  0%\n0.3  -0.1%\n0.6  -0.6%\n1  -1.2%','2000 mm')
        self.assertEqual(len(c.visible_results('0.44 μm')),1)
        self.assertEqual(len(c.visible_results('未标注波长')),1)
        self.assertEqual(c.maximum('未标注波长'),1.2)
        a.visible=False
        self.assertIsNone(c.maximum('0.44 μm'))
        a.visible=True;c.rename(a.id,'700 mm')
        self.assertEqual(a.name,'700 mm');c.remove([a.id])
        self.assertEqual(len(c.items),1)

    def test_repeated_wave_blocks_preserved(self):
        t=SAMPLE.read_text(encoding='utf-16');c=Collection()
        added=c.add_text(t+'\n'+t,'合并数据')
        self.assertEqual(len(added),2)
        self.assertEqual([len(d.curves) for d in added],[3,3])

    def test_invalid_paste_does_not_add(self):
        c=Collection()
        with self.assertRaises(ValueError):c.add_text('没有数值','测试')
        self.assertEqual(c.items,[])

    def test_no_distance_uses_placeholder(self):
        c=Collection()
        d=c.add_text('归一化半径  畸变(%)\n0  0%\n0.3  -0.1%\n0.6  -0.6%\n1  -1.2%','')[0]
        self.assertEqual(d.name,'双击输入')
        d2=c.add_text('归一化半径  畸变(%)\n0  0%\n0.3  -0.1%\n0.6  -0.6%\n1  -1.2%','2000 mm')[0]
        self.assertEqual(d2.name,'2000 mm')

    def test_fit_grade_boundaries(self):
        for value,key in [(None,'green'),(0,'green'),(5,'green'),(5.0001,'yellow'),(10,'yellow'),(10.0001,'red')]:
            self.assertEqual(fit_grade(value)[0],key)

    def test_distance_metadata_no_guessing(self):
        self.assertEqual(distance_name('lens.txt','结构 1 的 27'),'lens')
        self.assertEqual(distance_name('lens.txt','工作距离：1500 mm'),'1500 mm')
        self.assertEqual(distance_name('300mm.txt'),'300 mm')

    def test_known_model_fit(self):
        q=np.linspace(0,.7,101);d=.007*q*q-.012*q**4
        c=Curve('0','known','TXT','0.46 μm',1,101,'角度','畸变',np.rad2deg(np.arctan(q)).tolist(),d.tolist(),'angle','fraction')
        r=fit_curve(c)
        self.assertLess(r['max_error'],1e-12)
        np.testing.assert_allclose(r['coefficients'],[.007,-.012],atol=1e-12)

    def make_shape(self,coefficients):
        q=np.linspace(0,1,501);d=sum(c*q**(2*(i+1)) for i,c in enumerate(coefficients))
        return Curve('0','known.txt','TXT','0.46 μm',1,501,'角度','畸变',np.rad2deg(np.arctan(q)).tolist(),d.tolist(),'angle','fraction')

    def test_zero_one_two_reversals_and_model_selection(self):
        for coefficients,count,terms in [([.005,.001],0,2),([.005,-.005],1,2),([.005,-.015,.01],2,3)]:
            c=self.make_shape(coefficients)
            self.assertEqual(turning_points(c)['count'],count)
            r=Dataset('1','test','test.txt',{'0.46 μm':c}).result('0.46 μm')
            self.assertEqual(r['terms'],terms)
            self.assertLess(r['max_error'],1e-12)
            np.testing.assert_allclose(r['coefficients'],coefficients,atol=1e-10)

    def test_tiny_wave_does_not_add_turn(self):
        c=self.make_shape([.005,-.005])
        c.raw=(np.array(c.raw)+np.sin(np.arange(len(c.raw)))*1e-7).tolist()
        self.assertEqual(turning_points(c)['count'],1)

    def test_supplied_txt_has_one_turn_at_each_wave(self):
        c=Collection();dataset=c.add_bytes(SAMPLE.read_bytes(),'sample.txt')[0]
        for w in c.waves():
            r=dataset.result(w)
            self.assertEqual(r['turns']['count'],1)
            self.assertEqual(r['terms'],2)
            self.assertLess(r['max_error'],.02)


if __name__=='__main__':unittest.main(verbosity=2)
