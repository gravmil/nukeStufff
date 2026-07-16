import nuke

toolbar = nuke.menu('Nodes')
lcd_menu = toolbar.addMenu('LCD')
lcd_menu.addCommand('LCD Dot Matrix', lambda: nuke.createNode('LCD_DotMatrix'))
