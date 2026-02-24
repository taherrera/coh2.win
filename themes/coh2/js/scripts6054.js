(function ($, Drupal) {
  Drupal.behaviors.coh2 = {
    attach: function (context, settings) {
      $('.mobile-toggle', context).click(function() {
        var $mainnav = $('#block-mainnavigation');
        if ($mainnav.hasClass('open')) {
          $mainnav.removeClass('open');
        }
        else {
          $mainnav.addClass('open');
        }
        return false;
      });
      $('img').tooltip();

    }
  };
})(jQuery, Drupal);
