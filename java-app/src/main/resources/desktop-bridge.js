(function () {
  if (!navigator.clipboard) {
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: function (text) {
          try {
            window.opsmateClipboard.writeText(String(text));
            return Promise.resolve();
          } catch (error) {
            return Promise.reject(error);
          }
        }
      }
    });
  }
  window.pywebview = {
    api: {
      pick_folder: function () {
        return Promise.resolve(window.opsmateFiles.pickFolder());
      }
    }
  };
  window.opsmateAssistantDrop = {
    choose: function () {
      var result = window.opsmateFiles.pickAssistantFiles();
      if (result) this.receive(result);
    },
    accepts: function (x, y) {
      var target = document.elementFromPoint(x, y);
      return !!(target && target.closest(".asst-chat"));
    },
    receive: function (result) {
      var chat = document.querySelector(".asst-chat");
      if (chat) {
        chat.dispatchEvent(new CustomEvent("opsmate-native-drop", {
          detail: JSON.parse(result)
        }));
      }
    }
  };
  var originalClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (!this.download || !this.href.startsWith("blob:")) {
      return originalClick.apply(this, arguments);
    }
    var filename = this.download;
    fetch(this.href).then(function (response) {
      return response.blob();
    }).then(function (blob) {
      var reader = new FileReader();
      reader.onload = function () {
        try {
          window.opsmateFiles.download(filename, String(reader.result).split(",")[1]);
        } catch (error) {
          alert("保存失败：" + error);
        }
      };
      reader.readAsDataURL(blob);
    }).catch(function (error) {
      alert("下载失败：" + error);
    });
  };
})();
