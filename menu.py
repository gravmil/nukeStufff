import nuke

toolbar = nuke.menu('Nodes')

lcd_menu = toolbar.addMenu('LCD')
lcd_menu.addCommand('LCD Dot Matrix', lambda: nuke.createNode('LCD_DotMatrix'))

custom_menu = toolbar.addMenu('Custom')
custom_menu.addCommand('Remap Range', lambda: nuke.createNode('Remap_Range'))
