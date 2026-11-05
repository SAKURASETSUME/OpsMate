package com.opsmate;

import java.awt.Desktop;
import java.awt.FlowLayout;
import java.net.URI;
import javax.swing.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;

/** Browser fallback keeps an explicit native exit control owning the same backend. */
final class BrowserFallback {
    private BrowserFallback() { }
    static void open(String[] args,ServletWebServerApplicationContext existing) {
        var context=existing!=null&&existing.isActive()?existing:(ServletWebServerApplicationContext)SpringApplication.run(OpsMateApplication.class,args);
        URI address=URI.create("http://127.0.0.1:"+context.getWebServer().getPort()+"/index.html");
        SwingUtilities.invokeLater(() -> {
            JFrame frame=new JFrame("OpsMate 浏览器模式");
            frame.setLayout(new FlowLayout());
            frame.add(new JLabel("OpsMate 已启动，可在默认浏览器中使用。"));
            JButton open=new JButton("打开 OpsMate"),exit=new JButton("退出 OpsMate");
            Runnable browse=() -> {
                try { Desktop.getDesktop().browse(address); }
                catch (Exception unavailable) { JOptionPane.showMessageDialog(frame,"请在浏览器访问：\n"+address,"打开浏览器失败",JOptionPane.INFORMATION_MESSAGE); }
            };
            open.addActionListener(event -> browse.run());
            Runnable close=() -> { frame.dispose(); Thread.startVirtualThread(context::close); };
            exit.addActionListener(event -> close.run());
            frame.setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);
            frame.addWindowListener(new java.awt.event.WindowAdapter() {
                @Override public void windowClosing(java.awt.event.WindowEvent event) { close.run(); }
            });
            frame.add(open); frame.add(exit); frame.setSize(370,130); frame.setLocationRelativeTo(null); frame.setVisible(true);
            browse.run();
        });
    }
}
